"""Run manifest contents, and the answer-cache switch (default unchanged; disabled => no cached answer is ever used)."""

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from integration.eval import base_vs_rag
from integration.eval.run_manifest import (build_manifest, manifest_path_for, package_versions, prompt_template_hashes, quantization,
                                           sha256_text, write_manifest)
from integration.qa import system
from integration.qa.config import QAConfig
from integration.rag.rag_config import RagConfig
from query_router.base import RouteDecision

ROOT = Path(__file__).resolve().parents[2]


class _Details:
    quantization_level = "Q4_K_M"


class _Shown:
    details = _Details()


def _manifest(**kw):
    return build_manifest(ollama_show=lambda m: _Shown(), **kw)


# ---- manifest -----------------------------------------------------------------------------------------------------------
def test_manifest_has_every_required_section():
    m = _manifest(rag_config=RagConfig.b2(), qa_config=QAConfig(), index_dirs=[], extra={"arm": "B2"})
    for key in ("timestamp_utc", "model", "decoding", "prompt_template_sha256", "context_budget", "retrieval_flags", "indexes", "git",
                "packages", "hardware", "extra"):
        assert key in m
    assert m["model"]["quantization"] == "Q4_K_M" and m["model"]["name"]
    assert m["decoding"]["temperature"] == 0.0 and m["decoding"]["seed"] == 42
    assert "not set in code" in m["decoding"]["top_p"] and "not set in code" in m["decoding"]["max_tokens"]   # never guessed
    assert m["context_budget"]["shared_top_n"] == 6 and m["context_budget"]["per_source_budget"] == {"db_blocks": 5, "doc_blocks": 3}
    flags = m["retrieval_flags"]
    assert flags["rag_config"]["exclude_scifact"] is True and flags["rag_config"]["semantic_layer"] is False
    assert flags["qa_config"]["use_ontology"] is False and flags["qa_config"]["exclude_scifact"] is True
    assert m["extra"] == {"arm": "B2"}
    json.dumps(m, default=str)                                       # serialisable


def test_default_budget_is_recorded_as_none_not_invented():
    assert _manifest(rag_config=RagConfig())["context_budget"]["per_source_budget"] is None


def test_git_hash_is_the_real_head_and_dirty_flag_is_a_bool():
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    g = _manifest()["git"]
    assert g["commit"] == head and isinstance(g["dirty"], bool)


def test_package_versions_and_template_hashes():
    v = package_versions()
    assert set(v) >= {"torch", "transformers", "sentence-transformers", "faiss-cpu", "numpy"}
    h = prompt_template_hashes()
    assert {"rag_generate.SYSTEM_PROMPT", "qa_generation.SYSTEM_TEMPLATE", "e14a_eval.JUDGE_SYSTEM", "decomposer.SYSTEM"} <= set(h)
    assert all(len(x) == 64 for x in h.values()) and h == prompt_template_hashes()      # stable
    assert sha256_text("a") != sha256_text("b")


def test_quantization_unavailable_is_reported_not_faked():
    def boom(model):
        raise ConnectionError("no server")
    assert quantization("m", boom).startswith("unavailable:")


def test_index_info_records_hash_count_and_composition():
    clean = ROOT / "data" / "experiments" / "combined_retrieval_clean" / "vectorstore"
    if not clean.exists():
        pytest.skip("clean index not built")
    info = _manifest(index_dirs=[clean])["indexes"][0]
    assert info["chunks"] == 1420 and info["composition"] == {"NovaTel Synthetic": 258, "TRAI": 1162}
    assert len(info["faiss.index_sha256"]) == 64
    manifest = json.loads((clean / "index_manifest.json").read_text(encoding="utf-8"))
    assert manifest["sha256"]["faiss.index"] == info["faiss.index_sha256"]


def test_manifest_is_written_next_to_the_results(tmp_path, monkeypatch):
    import integration.eval.run_manifest as rm
    monkeypatch.setattr(rm, "quantization", lambda model, show=None: "Q4_K_M")
    out = write_manifest(tmp_path / "metrics.json", rag_config=RagConfig())
    assert out == manifest_path_for(tmp_path / "metrics.json") == tmp_path / "metrics.manifest.json" and out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["model"]["quantization"] == "Q4_K_M"


# ---- answer cache (E14a harness) --------------------------------------------------------------------------------------------
class _Retr:
    def __init__(self, n=0):
        self.n = n

    def search(self, q, **kw):
        return []

    def close(self):
        pass


class _FakeClient:
    model = "fake"

    def chat(self, system, user):
        return "FRESH BASE ANSWER"


class _FakePipeline:
    def __init__(self):
        self.llm_client, self.structured, self.unstructured = _FakeClient(), _Retr(), _Retr()

    def close(self):
        pass


def _run_stage_a(monkeypatch, tmp_path, use_cache):
    out = tmp_path / "bvr"
    out.mkdir()
    qs = {"queries": [{"query_id": "Q1", "question": "what is x?", "intended_category": "unstructured_synthetic",
                       "reference_evidence": {"kind": "document_ids", "expected_document_ids": ["D"]}}]}
    (out / "queryset.json").write_text(json.dumps(qs), encoding="utf-8")
    monkeypatch.setattr(base_vs_rag, "OUT_DIR", out)
    monkeypatch.setattr(base_vs_rag, "QUERYSET_PATH", out / "queryset.json")
    monkeypatch.setattr(base_vs_rag, "ANSWERS_PATH", out / "answers.jsonl")
    monkeypatch.setattr(base_vs_rag, "_cached_rag_answers", lambda: {"Q1": "CACHED ANSWER FROM AN EARLIER RUN"})
    import integration.rag.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "RagPipeline", _FakePipeline)
    base_vs_rag.stage_a_generate(use_cache=use_cache)
    return json.loads((out / "answers.jsonl").read_text(encoding="utf-8").splitlines()[0])


def test_default_still_reuses_the_cached_answer(monkeypatch, tmp_path):
    rec = _run_stage_a(monkeypatch, tmp_path, use_cache=True)
    assert rec["rag_answer"] == "CACHED ANSWER FROM AN EARLIER RUN" and rec["rag_answer_reused_from_subset_run"] is True


def test_cache_disabled_never_uses_a_cached_answer(monkeypatch, tmp_path):
    rec = _run_stage_a(monkeypatch, tmp_path, use_cache=False)
    assert rec["rag_answer_reused_from_subset_run"] is False and "CACHED" not in rec["rag_answer"]


def test_cache_for_run_helper():
    assert base_vs_rag._cache_for_run(False) == {}


@pytest.mark.parametrize("argv,expected", [
    (["x", "generate"], ("generate", None, True)),
    (["x", "generate", "3"], ("generate", 3, True)),
    (["x", "generate", "--no-cache"], ("generate", None, False)),
    (["x", "generate", "5", "--no-cache"], ("generate", 5, False)),
    (["x"], ("help", None, True)),
])
def test_cli_flag_is_parsed(argv, expected):
    assert base_vs_rag._parse_cli(argv) == expected


# ---- QA backend has no answer cache -----------------------------------------------------------------------------------------
def test_qa_backend_regenerates_on_every_call(monkeypatch):
    calls = []

    class S:
        def can_execute(self, q):
            return True, {}

        def search(self, q, cfg, origin="original"):
            from integration.qa.evidence import structured_evidence
            ev = structured_evidence({"record_id": "1", "dataset": "invoices", "score": 1.0, "retrieval_method": "exact_filter",
                                      "content": "invoice 1 status Overdue", "metadata": {"status": "Overdue"}},
                                     parsed={"table": "invoices"}, sub_query=q, origin=origin, primary_key="invoice_id")
            return [ev], {"executed": True, "n_results": 1}

    monkeypatch.setattr(system, "_route", lambda q, cfg: (RouteDecision.from_label("structured", router_name="f", model_id="f"), {}))
    monkeypatch.setattr(system, "_STRUCTURED", S())
    monkeypatch.setattr(system, "get_unstructured", lambda: types.SimpleNamespace(search=lambda *a, **k: ([], {})))
    monkeypatch.setattr(system, "generate", lambda q, ev, cfg, sq=None: calls.append(q) or "Invoice 1 is Overdue. [E1]")
    cfg = QAConfig(verifier="lexical", router_conf_threshold=0.0)
    system.answer_query("Show invoices", cfg)
    system.answer_query("Show invoices", cfg)
    assert len(calls) == 2          # the identical question reaches the generator twice: nothing is memoised
