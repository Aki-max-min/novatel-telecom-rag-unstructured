"""FA_GRAPH_JSON: the one switch that selects which graph.json a final-ablation run reads (eval/final_ablation/harness_fa.py).

(1) unset -> the repository default (integration.rag.semantic_layer.GRAPH_JSON), behaviour exactly as before;
(2) set   -> that file (relative values from the repository root) reaches every layer as SemanticLayer(graph_path=...);
(3) a MANIFEST.json beside the file whose files_sha256 entry differs from the file -> GraphManifestMismatch, nothing built.
No model, index, Ollama or Person B module is loaded: the layer classes are replaced by fakes that record their constructor arguments.

    .venv_colpali/Scripts/python.exe -m pytest eval/final_ablation/tests/test_graph_path_switch.py -p no:cacheprovider -q
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness_fa as fa  # noqa: E402

from integration.rag import semantic_layer  # noqa: E402

GRAPH = json.dumps({"schema_version": "test", "nodes": [], "edges": []})


def _graph(tmp_path: Path, manifest_sha: str | None = None) -> Path:
    p = tmp_path / "graph.json"
    p.write_text(GRAPH, encoding="utf-8")
    if manifest_sha is not None:
        (tmp_path / "MANIFEST.json").write_text(json.dumps({"files_sha256": {"graph.json": manifest_sha}}), encoding="utf-8")
    return p


class _Recorder:
    """Stands in for GraphOnlyLayer / OntologyOnlyLayer: records the keyword arguments, builds nothing."""
    calls: list[dict] = []

    def __init__(self, *args, **kw):
        self.args, self.kw = args, kw
        _Recorder.calls.append(kw)


@pytest.fixture
def fake_layers(monkeypatch):
    _Recorder.calls = []
    monkeypatch.setattr(fa, "GraphOnlyLayer", _Recorder)
    monkeypatch.setattr(fa, "OntologyOnlyLayer", _Recorder)
    return _Recorder


# ---- (1) default -----------------------------------------------------------------------------------------------------------------------
def test_unset_means_the_repository_default_path():
    path, source = fa.graph_path_from_env({})
    assert path == semantic_layer.GRAPH_JSON == fa.ROOT / "knowledge_graph" / "output" / "graph.json" and source == "default"
    assert fa.graph_path_from_env({"FA_GRAPH_JSON": ""}) == (semantic_layer.GRAPH_JSON, "default")     # empty counts as unset


@pytest.mark.skipif(not semantic_layer.GRAPH_JSON.is_file(), reason="knowledge_graph/output/graph.json not built locally")
def test_unset_builds_every_layer_on_the_default_graph(monkeypatch, fake_layers):
    monkeypatch.delenv("FA_GRAPH_JSON", raising=False)
    layers = fa.build_layers()
    assert set(layers) == set(fa.LAYER_ARMS) and len(fake_layers.calls) == len(fa.LAYER_ARMS)
    assert all(c["graph_path"] == semantic_layer.GRAPH_JSON for c in fake_layers.calls)
    g = fa.resolve_graph({})
    assert g["source"] == "default" and g["sha256"] == hashlib.sha256(semantic_layer.GRAPH_JSON.read_bytes()).hexdigest()


# ---- (2) env var set -------------------------------------------------------------------------------------------------------------------
def test_env_path_is_used_for_every_layer(monkeypatch, tmp_path, fake_layers):
    p = _graph(tmp_path)
    monkeypatch.setenv("FA_GRAPH_JSON", str(p))
    g = fa.resolve_graph()
    assert g["path"] == p and g["source"] == "FA_GRAPH_JSON" and g["sha256"] == hashlib.sha256(GRAPH.encode("utf-8")).hexdigest()
    assert g["manifest"] is None and g["manifest_checked"] is False
    layers = fa.build_layers()
    assert set(layers) == set(fa.LAYER_ARMS)
    assert all(c["graph_path"] == p for c in fake_layers.calls)
    assert {c["use_related_links"] for c in fake_layers.calls} == {fa.LAYER_SPECS[a][2] for a in fa.LAYER_ARMS}   # other settings untouched


def test_relative_env_path_is_taken_from_the_repository_root():
    path, source = fa.graph_path_from_env({"FA_GRAPH_JSON": "data/experiments/frozen_graph_v1/graph.json"})
    assert path == fa.ROOT / "data" / "experiments" / "frozen_graph_v1" / "graph.json" and source == "FA_GRAPH_JSON"


def test_matching_frozen_manifest_is_recorded_as_checked(tmp_path):
    p = _graph(tmp_path, manifest_sha=hashlib.sha256(GRAPH.encode("utf-8")).hexdigest())
    g = fa.resolve_graph({"FA_GRAPH_JSON": str(p)})
    assert g["manifest_checked"] is True and g["manifest_sha256"] == g["sha256"] and g["manifest"] == str(tmp_path / "MANIFEST.json")


# ---- (3) hash mismatch -----------------------------------------------------------------------------------------------------------------
def test_frozen_manifest_mismatch_raises_before_any_layer_is_built(monkeypatch, tmp_path, fake_layers):
    p = _graph(tmp_path, manifest_sha="0" * 64)
    monkeypatch.setenv("FA_GRAPH_JSON", str(p))
    with pytest.raises(fa.GraphManifestMismatch, match="differs from its frozen manifest"):
        fa.resolve_graph()
    with pytest.raises(fa.GraphManifestMismatch):
        fa.build_layers()
    assert fake_layers.calls == []


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        fa.resolve_graph({"FA_GRAPH_JSON": str(tmp_path / "nope.json")})


# ---- experiment ids and the Rig constructor (2026-11-15) ---------------------------------------------------------------------------------
def test_graph_v1_regression_has_its_own_results_folder():
    e, ref = fa.EXPERIMENTS["graph_v1_regression"], fa.EXPERIMENTS["graph_merge_fix"]
    assert e["res"] == "graph_v1_regression" and e["res"] != ref["res"]
    assert e["new"] == ref["new"] == ["GF", "GFL"] and e["reused"] == ref["reused"] == ["B2"] and e["comparisons"] == ref["comparisons"]
    assert {x["res"] for x in fa.EXPERIMENTS.values()} == set(fa.EXPERIMENTS)          # one folder per id, no sharing
    assert e["allowed_code_change_prefixes"] == ("knowledge_graph/", "hybrid/")


def test_every_experiment_id_has_a_manifest_description():
    import fa_generate
    assert set(fa_generate.EXPERIMENT_DESCRIPTIONS) == set(fa.EXPERIMENTS)
    assert fa_generate.FIXED_MERGE_EXPERIMENTS <= set(fa.EXPERIMENTS)


def test_rig_builds_no_layer_on_the_default_graph(monkeypatch, tmp_path, fake_layers):
    """Fresh clone: knowledge_graph/output/graph.json may be absent; Rig must only build this experiment's layers on the selected graph."""
    import integration.rag.pipeline as pipeline
    import query_router.registry as registry

    def boom(*a, **kw):
        raise AssertionError("v3 default-graph layer constructed")
    for name in ("SemanticLayer", "OntologyOnlyLayer", "DocGraphOnlyLayer"):
        monkeypatch.setattr(fa.h, name, boom)
    monkeypatch.setattr(fa.h, "CountingClient", lambda: "client")
    monkeypatch.setattr(pipeline, "RagPipeline", lambda **kw: ("pipeline", sorted(kw)))
    monkeypatch.setattr(registry, "build_router", lambda name, opts: ("router", name, opts))
    p = _graph(tmp_path)
    monkeypatch.setenv("FA_GRAPH_JSON", str(p))
    rig = fa.Rig()
    assert rig.graph["path"] == p and rig.client == "client" and rig.pipeline[0] == "pipeline" and rig.router[0] == "router"
    assert set(rig.layers) == set(fa.LAYER_ARMS) and all(c["graph_path"] == p for c in fake_layers.calls)
