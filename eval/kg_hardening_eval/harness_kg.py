"""
KG-hardening evaluation harness (NEW code; nothing under eval/perf_report/ or integration/ is edited).

It REUSES the v3 measurement harness (eval/perf_report/harness.py: Rig, TimeoutClient, CachedJudge, score_answer, citation_check, prompts,
decoding settings, latency rules) unchanged, and only (a) redirects its output paths to results/kg_hardening_eval/, (b) replaces the arm table
with the four configurations of this evaluation, and (c) builds the three semantic layers these arms need. The v3 harness reads its
module-level names (RES, RAW, SCORED, JUDGE_CACHE, ARMS, FULL_ARMS, arm_settings) at call time, so they are reassigned here once, on import.

ARMS (same model, prompts, decoding, seed, SciFact filter ON, answer cache OFF, 5 db + 3 doc prompt budget in every arm):
  B2          RAG baseline + per-source budget (RagConfig.b2()); no router, no semantic layer.               == v3 arm "B2"
  C_V0        B2 + router + semantic layer with the LEGACY graph_expand profile (no hardening kwargs),        == v3 arm "C" except that
              use_related_links=False, citation check.                                                       the RELATED_TO hop is explicitly off
  C_V1        C_V0 but graph_expand(hub_fraction=0.05, specificity=True, max_documents=3)  (Person B's best-by-the-rule profile).
  C_V1_links  C_V1 + use_related_links=True (our semantic_layer.py RELATED_TO hop; 47 of 84 links resolve after the alias build).

use_related_links: the v3 arm C ran SemanticLayer's default (True) at a time when 0 of 84 links resolved, so the hop added nothing; now that
47 resolve, C_V0 and C_V1 set it False explicitly so that only C_V1_links carries the link effect.

Judge: the v3 judge (same local model, temperature 0, seed 42, E14a prompts). Its prompt cache is seeded READ-ONLY from
results/perf_report/judge_cache.jsonl (identical prompt -> identical v3 verdict); new verdicts are appended only to this experiment's cache.
Every arm is judged at the "full" level (correctness, relevance, hallucination vs reference, groundedness, hallucination vs context), and every
arm gets the citation check, so B2 is scored on everything this time.
"""

from __future__ import annotations

import functools
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERF = ROOT / "eval" / "perf_report"
for p in (str(ROOT), str(ROOT / "structured"), str(PERF), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import harness as h  # noqa: E402  (eval/perf_report/harness.py, the v3 harness, unchanged)

from integration.rag.rag_config import RagConfig  # noqa: E402
from integration.rag.semantic_layer import SemanticLayer  # noqa: E402

EXP = ROOT / "eval" / "kg_hardening_eval"
RES = ROOT / "results" / "kg_hardening_eval"
RAW = RES / "raw_answers.jsonl"
SCORED = RES / "scored_answers.jsonl"
JUDGE_CACHE = RES / "judge_cache.jsonl"
FAILURES = RES / "failures.jsonl"
LOG = RES / "run_log.txt"
V3_RES = ROOT / "results" / "perf_report"
V3_JUDGE_CACHE = V3_RES / "judge_cache.jsonl"
V3_RAW = V3_RES / "raw_answers.jsonl"
V3_SCORED = V3_RES / "scored_answers.jsonl"

ARMS = ["B2", "C_V0", "C_V1", "C_V1_links"]
C_ARMS = ["C_V0", "C_V1", "C_V1_links"]
RUNS = 3
V1_OPTIONS = {"hub_fraction": 0.05, "specificity": True, "max_documents": 3}   # Person B's best-by-the-rule profile, exactly as given
MERGED_COMMIT = "700a5dd58e7d9be0c36518bb4e574f090d5a1a76"
HANDOFF_COMMIT = "83a8aa77523fe28dae4677443709bfb76c261d2c"
V3_COMMIT = "2fdffad77dd86f9e350bc69d0d58a64bae6250b1"

# ---- redirect the v3 harness to this experiment (its functions read these names at call time) ---------------------------------------
h.RES, h.RAW, h.SCORED, h.JUDGE_CACHE = RES, RAW, SCORED, JUDGE_CACHE
h.ARMS = ARMS
h.FULL_ARMS = set(ARMS)     # judging_level() -> "full" for every arm
h.MIN_ARMS = set()
h.ABLATION_ARMS = set()


class HardenedGraphLayer(SemanticLayer):
    """SemanticLayer whose graph_expand call carries Person B's E13 hardening keyword arguments (hub_fraction, specificity, max_documents).
    neighbours() is NOT overridden: it still calls self._graph_expand(seeds, graph_index, bridges=..., limit=...); the partial adds the
    keyword arguments to that same call. With an empty options dict the layer is the legacy one, call for call."""

    def __init__(self, graph_expand_options: dict, **kw):
        super().__init__(**kw)
        self.graph_expand_options = dict(graph_expand_options)
        if self.graph_expand_options:
            self._graph_expand = functools.partial(self._graph_expand, **self.graph_expand_options)


def arm_settings(arm: str) -> dict:
    """What each arm switches on (recorded in the manifest, checked against the layer object before every generation)."""
    b2 = RagConfig.b2().as_dict()
    c = {"retrieval": True, "rag_config": b2, "router": True, "citation_check": True}
    return {
        "B2": {"retrieval": True, "rag_config": b2, "layer": None, "router": False, "graph_expand_options": None, "use_related_links": None},
        "C_V0": {**c, "layer": "C_V0", "graph_expand_options": {}, "use_related_links": False},
        "C_V1": {**c, "layer": "C_V1", "graph_expand_options": dict(V1_OPTIONS), "use_related_links": False},
        "C_V1_links": {**c, "layer": "C_V1_links", "graph_expand_options": dict(V1_OPTIONS), "use_related_links": True},
    }[arm]


h.arm_settings = arm_settings      # h.Rig.generate looks this name up in the harness module


def build_layers() -> dict:
    mc = RagConfig().semantic_max_chunks_per_doc
    return {"C_V0": HardenedGraphLayer({}, max_chunks_per_doc=mc, use_related_links=False),
            "C_V1": HardenedGraphLayer(V1_OPTIONS, max_chunks_per_doc=mc, use_related_links=False),
            "C_V1_links": HardenedGraphLayer(V1_OPTIONS, max_chunks_per_doc=mc, use_related_links=True)}


def check_layer(layer, s: dict) -> None:
    """The layer object must carry exactly the settings the arm table declares (raises before any generation otherwise)."""
    if layer.use_related_links != s["use_related_links"]:
        raise RuntimeError(f"layer {s['layer']}: use_related_links={layer.use_related_links}, arm table says {s['use_related_links']}")
    if getattr(layer, "graph_expand_options", None) != s["graph_expand_options"]:
        raise RuntimeError(f"layer {s['layer']}: graph_expand_options={getattr(layer, 'graph_expand_options', None)}, "
                           f"arm table says {s['graph_expand_options']}")


class Rig(h.Rig):
    """The v3 Rig (models loaded once, same TimeoutClient / router / pipeline) with this experiment's three layers."""

    def __init__(self):
        super().__init__()
        self.layers = build_layers()

    def warm_up(self) -> None:
        self.client.chat(system="Reply with one word.", user="OK?")
        self.pipeline.structured.search("warm up")
        self.pipeline.unstructured.search("warm up", semantic=self.layers["C_V0"])
        try:
            self.router.route("warm up")
        except Exception:  # noqa: BLE001
            pass

    def generate(self, arm: str, q: dict, run: int) -> dict:
        s = arm_settings(arm)
        layer = self.layers[s["layer"]] if s["layer"] else None
        before = layer.stats["related_neighbours_added"] if layer else 0
        if layer is not None:
            check_layer(layer, s)
        rec = super().generate(arm, q, run)
        rec["arm_config"] = {key: s[key] for key in ("layer", "graph_expand_options", "use_related_links", "router", "rag_config")}
        if rec.get("semantic") is not None:
            rec["semantic"]["related_neighbours_added"] = layer.stats["related_neighbours_added"] - before
            rec["semantic"]["link_report"] = {key: layer.stats[key] for key in ("related_links_total", "related_links_dangling")}
        return rec


class Judge(h.CachedJudge):
    """v3 CachedJudge; cache seeded read-only from the v3 cache, new verdicts appended to this experiment's cache only."""

    def __init__(self, model: str = h.DEFAULT_MODEL):
        super().__init__(model)                       # loads JUDGE_CACHE (this experiment's file)
        self.v3_keys = set()
        self.v3_hits = 0
        if model == h.DEFAULT_MODEL:
            for r in h.read_jsonl(V3_JUDGE_CACHE):
                if r["key"] not in self.cache:
                    self.cache[r["key"]] = r["raw"]
                    self.v3_keys.add(r["key"])

    def chat(self, system: str, user: str, uncached: bool = False) -> str:
        key = hashlib.sha1((self.model + "\x00" + system + "\x00" + user).encode("utf-8")).hexdigest()
        if not uncached and key in self.v3_keys:
            self.v3_hits += 1
        return super().chat(system, user, uncached=uncached)


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    RES.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
