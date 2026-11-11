"""
Final component-ablation harness (NEW code; nothing under eval/perf_report/, eval/kg_hardening_eval/ or integration/ is edited).

It REUSES the v3 measurement harness (eval/perf_report/harness.py: Rig, TimeoutClient, CachedJudge, score_answer, citation_check, prompts,
decoding, latency rules; its OntologyOnlyLayer / DocGraphOnlyLayer subclasses) unchanged, redirects its output paths to
results/final_ablation/, and replaces the arm table with the arms that are GENERATED here. Four arms are REUSED, not re-run, from
results/kg_hardening_eval/ (B2, C_V0, C_V1, C_V1_links): fa_generate.py verifies that their code state is identical to HEAD for every
retrieval/generation module before the manifest is written.

Generated arms (same model, prompts, decoding, seed 42, temperature 0, SciFact filter ON, answer cache OFF, 3 runs):
  A    Base LLM, no retrieval (E14a BASE_SYSTEM_PROMPT).                                                        == v3 arm "A"
  B    RAG baseline: SQL + documents, RRF, SHARED 6-block prompt limit (RagConfig()), no per-source budget.       == v3 arm "B"
  R    B2 + the QA router only (auto chain laya_finetuned -> embedding -> rule decides the sources searched);      == v3 arm "router"
       no semantic layer.
  O    B2 + ontology concept hint only: concept hint -> canonical terms appended to the FAISS query; the graph    == v3 arm "ontology"
       list is switched off (OntologyOnlyLayer.neighbours -> []); router OFF.                                     (+ use_related_links=False)
  G0   B2 + legacy document-graph expansion only: graph_expand with NO hardening keyword arguments; the FAISS     == v3 arm "docgraph"
       query is NOT expanded with ontology terms, the query gate's graph weight (0.5 / 0.15 / 0.0) is kept        (+ use_related_links=False)
       (DocGraphOnlyLayer); use_related_links=False; router OFF.
  G1   G0 with graph_expand(hub_fraction=0.05, specificity=True, max_documents=3); use_related_links=False; router OFF.
  G1L  G1 with use_related_links=True (our integration/rag/semantic_layer.py RELATED_TO hop; 47 of 84 links resolve); router OFF.

"Router OFF" means exactly B2's behaviour: no routing, both sources searched (h.Rig.generate: use_structured = use_docs = True).

use_related_links: the v3 ontology/docgraph arms ran SemanticLayer's default (True) when 0 of 84 links resolved (the hop added nothing);
now 47 resolve, so O, G0 and G1 set it False explicitly and only G1L carries the link effect (same convention as the KG-hardening run).

Judge: the v3 judge (same local model, temperature 0, seed 42, E14a prompts), every arm at the "full" level; its prompt cache is seeded
READ-ONLY from results/perf_report/judge_cache.jsonl and results/kg_hardening_eval/judge_cache.jsonl; new verdicts go to this
experiment's own cache only.
"""

from __future__ import annotations

import functools
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PERF = ROOT / "eval" / "perf_report"
KG_EVAL = ROOT / "eval" / "kg_hardening_eval"
for p in (str(ROOT), str(ROOT / "structured"), str(KG_EVAL), str(PERF), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)
# sys.path order now: this dir, eval/perf_report, eval/kg_hardening_eval, structured, ROOT  ->  `import harness` / `import run_report`
# resolve to the v3 modules (eval/perf_report), `import harness_kg` to the KG-hardening module.

import harness as h  # noqa: E402  (eval/perf_report/harness.py, the v3 harness, unchanged)
import harness_kg as kg  # noqa: E402  (eval/kg_hardening_eval/harness_kg.py; imported for V1_OPTIONS and the reused arms' settings; it
#                                      re-points the v3 harness at results/kg_hardening_eval on import, which is undone right below)

from integration.rag.rag_config import RagConfig  # noqa: E402

EXP = ROOT / "eval" / "final_ablation"
RES = ROOT / "results" / "final_ablation"
RAW = RES / "raw_answers.jsonl"
SCORED = RES / "scored_answers.jsonl"
JUDGE_CACHE = RES / "judge_cache.jsonl"
FAILURES = RES / "failures.jsonl"
LOG = RES / "run_log.txt"
V3_RES = ROOT / "results" / "perf_report"
KG_RES = ROOT / "results" / "kg_hardening_eval"
V3_JUDGE_CACHE = V3_RES / "judge_cache.jsonl"
KG_JUDGE_CACHE = KG_RES / "judge_cache.jsonl"
KG_RAW = KG_RES / "raw_answers.jsonl"
KG_SCORED = KG_RES / "scored_answers.jsonl"
KG_MANIFEST = KG_RES / "run_manifest.json"

ARMS_NEW = ["A", "B", "R", "O", "G0", "G1", "G1L"]                 # generated here
ARMS_REUSED = ["B2", "C_V0", "C_V1", "C_V1_links"]                 # loaded from results/kg_hardening_eval/
ARMS_ALL = ["A", "B", "B2", "R", "O", "G0", "G1", "G1L", "C_V0", "C_V1", "C_V1_links"]   # table order
LAYER_ARMS = ["O", "G0", "G1", "G1L"]
GRAPH_ARMS = ["G0", "G1", "G1L"]
RUNS = 3
V1_OPTIONS = dict(kg.V1_OPTIONS)        # {"hub_fraction": 0.05, "specificity": True, "max_documents": 3}, exactly as given
V3_COMMIT = kg.V3_COMMIT
KG_CODE_DIRS = ["integration/", "structured/", "knowledge_graph/", "hybrid/", "query_router/", "ontology/", "eval/perf_report/",
                "eval/kg_hardening_eval/harness_kg.py", "data/eval/"]   # must be identical between the reused arms' commit and HEAD

# ---- redirect the v3 harness to THIS experiment (undoes harness_kg's redirection) --------------------------------------------------------
h.RES, h.RAW, h.SCORED, h.JUDGE_CACHE = RES, RAW, SCORED, JUDGE_CACHE
h.ARMS = ARMS_NEW
h.FULL_ARMS = set(ARMS_NEW)      # judging_level() -> "full" for every generated arm
h.MIN_ARMS = set()
h.ABLATION_ARMS = set()


class GraphOnlyLayer(h.DocGraphOnlyLayer):
    """v3 DocGraphOnlyLayer (no ontology terms in the FAISS query, gate weight kept) whose graph_expand call carries Person B's hardening
    keyword arguments. neighbours() is not overridden; the partial adds the arguments to the same call. Empty options = legacy call."""

    def __init__(self, graph_expand_options: dict, **kw):
        super().__init__(**kw)
        self.graph_expand_options = dict(graph_expand_options)
        if self.graph_expand_options:
            self._graph_expand = functools.partial(self._graph_expand, **self.graph_expand_options)


class OntologyOnlyLayer(h.OntologyOnlyLayer):
    """v3 OntologyOnlyLayer (neighbours -> []); records that no graph options apply."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.graph_expand_options = None


def arm_settings(arm: str) -> dict:
    """What each GENERATED arm switches on (recorded in the manifest and in every raw record, checked against the layer object before
    every generation). The reused arms' settings come from harness_kg.arm_settings (recorded in their own manifest)."""
    base, b2 = RagConfig().as_dict(), RagConfig.b2().as_dict()
    off = {"router": False, "graph_expand_options": None, "use_related_links": None, "ontology_query_terms": None}
    table = {
        "A": {"retrieval": False, "rag_config": None, "layer": None, **off},
        "B": {"retrieval": True, "rag_config": base, "layer": None, **off},
        "R": {"retrieval": True, "rag_config": b2, "layer": None, **off, "router": True},
        "O": {"retrieval": True, "rag_config": b2, "layer": "O", "router": False, "graph_expand_options": None, "use_related_links": False,
              "ontology_query_terms": True},
        "G0": {"retrieval": True, "rag_config": b2, "layer": "G0", "router": False, "graph_expand_options": {}, "use_related_links": False,
               "ontology_query_terms": False},
        "G1": {"retrieval": True, "rag_config": b2, "layer": "G1", "router": False, "graph_expand_options": dict(V1_OPTIONS), "use_related_links": False,
               "ontology_query_terms": False},
        "G1L": {"retrieval": True, "rag_config": b2, "layer": "G1L", "router": False, "graph_expand_options": dict(V1_OPTIONS), "use_related_links": True,
                "ontology_query_terms": False},
    }
    if arm in table:
        return table[arm]
    return kg.arm_settings(arm)            # B2 / C_V0 / C_V1 / C_V1_links (reused)


h.arm_settings = arm_settings      # h.Rig.generate looks this name up in the harness module (undoes harness_kg's assignment)


def build_layers() -> dict:
    mc = RagConfig().semantic_max_chunks_per_doc
    return {"O": OntologyOnlyLayer(max_chunks_per_doc=mc, use_related_links=False),
            "G0": GraphOnlyLayer({}, max_chunks_per_doc=mc, use_related_links=False),
            "G1": GraphOnlyLayer(V1_OPTIONS, max_chunks_per_doc=mc, use_related_links=False),
            "G1L": GraphOnlyLayer(V1_OPTIONS, max_chunks_per_doc=mc, use_related_links=True)}


def check_layer(layer, s: dict) -> None:
    """The layer object must carry exactly the settings the arm table declares (raises before any generation otherwise)."""
    if layer.use_related_links != s["use_related_links"]:
        raise RuntimeError(f"layer {s['layer']}: use_related_links={layer.use_related_links}, arm table says {s['use_related_links']}")
    if getattr(layer, "graph_expand_options", "missing") != s["graph_expand_options"]:
        raise RuntimeError(f"layer {s['layer']}: graph_expand_options={getattr(layer, 'graph_expand_options', 'missing')}, arm table says {s['graph_expand_options']}")
    is_onto = isinstance(layer, h.OntologyOnlyLayer)
    if is_onto != bool(s["ontology_query_terms"]):
        raise RuntimeError(f"layer {s['layer']}: ontology_query_terms={is_onto}, arm table says {s['ontology_query_terms']}")
    if not is_onto and not isinstance(layer, h.DocGraphOnlyLayer):
        raise RuntimeError(f"layer {s['layer']}: expected a DocGraphOnlyLayer, got {type(layer).__name__}")


class Rig(h.Rig):
    """The v3 Rig (models loaded once, same TimeoutClient / router / pipeline) with this experiment's four layers."""

    def __init__(self):
        super().__init__()
        self.layers = build_layers()

    def warm_up(self) -> None:
        self.client.chat(system="Reply with one word.", user="OK?")
        self.pipeline.structured.search("warm up")
        self.pipeline.unstructured.search("warm up", semantic=self.layers["G0"])
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
        rec["arm_config"] = {key: s[key] for key in ("layer", "graph_expand_options", "use_related_links", "ontology_query_terms", "router", "rag_config", "retrieval")}
        if rec.get("semantic") is not None:
            rec["semantic"]["related_neighbours_added"] = layer.stats["related_neighbours_added"] - before
            rec["semantic"]["link_report"] = {key: layer.stats[key] for key in ("related_links_total", "related_links_dangling")}
            if isinstance(layer, h.OntologyOnlyLayer):
                rec["semantic"]["normalised_query"] = layer.normalise_query(q["query"])[0]
        return rec


class Judge(h.CachedJudge):
    """v3 CachedJudge; cache seeded read-only from the v3 and KG-hardening caches, new verdicts appended to this experiment's cache only."""

    def __init__(self, model: str = h.DEFAULT_MODEL):
        super().__init__(model)                       # loads JUDGE_CACHE (this experiment's file)
        self.seed_keys: set[str] = set()
        self.seed_hits = 0
        if model == h.DEFAULT_MODEL:
            for path in (V3_JUDGE_CACHE, KG_JUDGE_CACHE):
                for r in h.read_jsonl(path):
                    if r["key"] not in self.cache:
                        self.cache[r["key"]] = r["raw"]
                        self.seed_keys.add(r["key"])

    def chat(self, system: str, user: str, uncached: bool = False) -> str:
        key = hashlib.sha1((self.model + "\x00" + system + "\x00" + user).encode("utf-8")).hexdigest()
        if not uncached and key in self.seed_keys:
            self.seed_hits += 1
        return super().chat(system, user, uncached=uncached)


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    RES.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_reused(check_counts: bool = True) -> tuple[dict, dict]:
    """The four reused arms' raw and scored records from results/kg_hardening_eval/, keyed (arm, id, run); verifies 126 records per arm,
    arm labels, and that every record's stored arm_config equals harness_kg.arm_settings for that arm."""
    raw = {(r["arm"], r["id"], r["run"]): r for r in h.read_jsonl(KG_RAW) if r["arm"] in ARMS_REUSED}
    scored = {(s["arm"], s["id"], s["run"]): s for s in h.read_jsonl(KG_SCORED) if s["arm"] in ARMS_REUSED}
    if check_counts:
        for arm in ARMS_REUSED:
            n_raw = sum(1 for key in raw if key[0] == arm)
            n_sc = sum(1 for key in scored if key[0] == arm)
            if n_raw != 126 or n_sc != 126:
                raise RuntimeError(f"reused arm {arm}: {n_raw} raw / {n_sc} scored records, expected 126 / 126")
            want = kg.arm_settings(arm)
            for key, r in raw.items():
                if key[0] != arm:
                    continue
                got = r.get("arm_config") or {}
                for field in ("layer", "graph_expand_options", "use_related_links", "router"):
                    if got.get(field) != want.get(field):
                        raise RuntimeError(f"reused arm {arm} {key}: arm_config.{field}={got.get(field)!r} but harness_kg says {want.get(field)!r}")
    return raw, scored
