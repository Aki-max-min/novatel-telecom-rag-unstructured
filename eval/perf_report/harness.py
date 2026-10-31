"""
Measurement harness library (NEW code, nothing in the repository is edited). Used by run_generate.py, run_score.py, run_report.py.

ARMS (all use the same model, prompts, decoding settings and seed; SciFact filter ON unless stated):
  A          Base LLM, no retrieval (E14a BASE_SYSTEM_PROMPT).
  B          E14a configuration: SQL + documents, RRF, SHARED 6-block context, [E#]-cited answers; no answer cache.
  B2         B + per-source budget, 5 database + 3 document blocks (RagConfig.b2()). The two numbers come from the E14a failure
             analysis on the SAME 22 questions that are evaluated; they are never tuned.
  router     B2 + the QA router (auto chain laya_finetuned -> embedding -> rule) deciding which sources are searched.
  ontology   B2 + ONLY the ontology half of the semantic layer (concept hint -> canonical terms appended to the FAISS query).
  docgraph   B2 + ONLY the document-graph half (graph_expand neighbours merged by weighted RRF at the gate weight).
  C          B2 + full semantic layer (ontology + document graph) + the router, and every answer is citation-checked by the project's
             verifier (flagging only; the answer text is never altered).
  B_scifact_off  B with the SciFact filter OFF (reproduction check, original 22 questions only).
Structured KG: not wired into retrieval -> "not run".

The pipeline below calls the same functions as integration.rag.pipeline.RagPipeline.run_query (structured search, document search,
reciprocal_rank_fusion, build_context, generate_answer); it only (a) asks the searcher for 10 ranked chunks and gives the prompt the first 5
(identical to the default 5 because the order is the same), and (b) records the evidence ids. Ontology-only / graph-only are built by
subclassing SemanticLayer here, so no repository code is changed.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import sys
import time
from pathlib import Path

import ollama

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "structured"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from integration.eval import base_vs_rag as e14  # noqa: E402
from integration.qa import citations as cit  # noqa: E402
from integration.qa.config import QAConfig  # noqa: E402
from integration.rag.context_builder import DEFAULT_TOP_N, build_context  # noqa: E402
from integration.rag.fuse import reciprocal_rank_fusion  # noqa: E402
from integration.rag.generate import generate_answer  # noqa: E402
from integration.rag.llm_client import DEFAULT_MODEL, OllamaClient  # noqa: E402
from integration.rag.pipeline import RERANK_TOP_K  # noqa: E402
from integration.rag.rag_config import RagConfig  # noqa: E402
from integration.rag.semantic_layer import SemanticLayer  # noqa: E402

PERF = ROOT / "eval" / "perf_report"
RES = ROOT / "results" / "perf_report"
QUESTIONS = PERF / "questions.jsonl"
RAW = RES / "raw_answers.jsonl"
SCORED = RES / "scored_answers.jsonl"
JUDGE_CACHE = RES / "judge_cache.jsonl"
ARMS = ["A", "B", "B2", "router", "ontology", "docgraph", "C"]
REPRO_ARM = "B_scifact_off"
SEED_NOTE = "temperature 0 and seed 42 (OllamaClient defaults)"


# ---------------------------------------------------------------------------------------------------------------------------------
# io
# ---------------------------------------------------------------------------------------------------------------------------------
def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def append_jsonl(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        f.flush()


def load_questions() -> list[dict]:
    return read_jsonl(QUESTIONS)


# ---------------------------------------------------------------------------------------------------------------------------------
# generation side
# ---------------------------------------------------------------------------------------------------------------------------------
class CountingClient(OllamaClient):
    """Same call options as OllamaClient (temperature, seed); additionally keeps Ollama's token counters of the last call."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def chat(self, system: str, user: str) -> str:
        r = ollama.chat(model=self.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                        options={"temperature": self.temperature, "seed": self.seed})
        self.prompt_tokens = r.get("prompt_eval_count") or 0
        self.completion_tokens = r.get("eval_count") or 0
        return r["message"]["content"]


class OntologyOnlyLayer(SemanticLayer):
    """Ontology term normalisation only: the graph list is switched off (the pipeline then adds no graph candidates)."""

    def neighbours(self, seed_documents, known_documents):
        self.link_report(known_documents)
        return []


class DocGraphOnlyLayer(SemanticLayer):
    """Document-graph expansion only: the FAISS query is NOT expanded with ontology terms; the gate weight is kept."""

    def normalise_query(self, question):
        return question, self.analyse(question)


def arm_settings(arm: str) -> dict:
    """What each arm switches on, as recorded in the manifest and the report."""
    base = RagConfig()
    b2 = RagConfig.b2()
    return {
        "A": {"retrieval": False},
        "B": {"retrieval": True, "rag_config": base.as_dict(), "layer": None, "router": False},
        "B2": {"retrieval": True, "rag_config": b2.as_dict(), "layer": None, "router": False},
        "router": {"retrieval": True, "rag_config": b2.as_dict(), "layer": None, "router": True},
        "ontology": {"retrieval": True, "rag_config": b2.as_dict(), "layer": "ontology_only", "router": False},
        "docgraph": {"retrieval": True, "rag_config": b2.as_dict(), "layer": "docgraph_only", "router": False},
        "C": {"retrieval": True, "rag_config": b2.as_dict(), "layer": "full", "router": True, "citation_check": True},
        REPRO_ARM: {"retrieval": True, "rag_config": RagConfig(exclude_scifact=False).as_dict(), "layer": None, "router": False},
    }[arm]


class Rig:
    """Loads every model once and runs one (arm, question) generation."""

    def __init__(self):
        from integration.rag.pipeline import RagPipeline
        self.client = CountingClient()
        self.pipeline = RagPipeline(llm_client=self.client, config=RagConfig())     # models loaded once; config switched per arm below
        self.layers = {"full": SemanticLayer(max_chunks_per_doc=RagConfig().semantic_max_chunks_per_doc),
                       "ontology_only": OntologyOnlyLayer(max_chunks_per_doc=RagConfig().semantic_max_chunks_per_doc),
                       "docgraph_only": DocGraphOnlyLayer(max_chunks_per_doc=RagConfig().semantic_max_chunks_per_doc)}
        from query_router.registry import build_router
        self.qa_cfg = QAConfig()
        self.router = build_router(self.qa_cfg.router, {"chain": self.qa_cfg.router_chain})

    def warm_up(self) -> None:
        self.client.chat(system="Reply with one word.", user="OK?")
        self.pipeline.structured.search("warm up")
        self.pipeline.unstructured.search("warm up", semantic=self.layers["full"])
        try:
            self.router.route("warm up")
        except Exception:  # noqa: BLE001
            pass

    # ---- routing (router / C arms) -----------------------------------------------------------------------------------------
    def route(self, question: str) -> dict:
        try:
            d = self.router.route(question)
            label = d.label
            low = d.confidence < self.qa_cfg.router_conf_threshold and label != "out_of_scope"
            return {"router": d.router_name, "label": label, "confidence": d.confidence, "final": "hybrid" if low else label,
                    "low_confidence_to_hybrid": low, "latency_ms": d.latency_ms, "error": None}
        except Exception as exc:  # noqa: BLE001  -- a router failure degrades to hybrid, recorded
            return {"router": None, "label": None, "confidence": None, "final": "hybrid", "low_confidence_to_hybrid": False,
                    "latency_ms": None, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    # ---- one generation ---------------------------------------------------------------------------------------------------------
    def generate(self, arm: str, q: dict, run: int) -> dict:
        s = arm_settings(arm)
        question = q["query"]
        rec = {"arm": arm, "id": q["id"], "run": run, "category": q["category"], "is_core": q["is_core"], "query": question,
               "cached": False, "model": self.client.model, "route": None, "structured_status": None, "semantic": None}
        self.client.prompt_tokens = self.client.completion_tokens = 0
        t0 = time.perf_counter()
        if not s["retrieval"]:
            rec["answer"] = self.client.chat(system=e14.BASE_SYSTEM_PROMPT, user=question)
            rec.update(evidence=[], context_text="", structured_ids=[], doc_top10=[], doc_top10_chunks=[], prompt_blocks=[],
                       abstained=False)
        else:
            cfg = RagConfig(**{k: v for k, v in s["rag_config"].items()})
            self.pipeline.unstructured.exclude_scifact = cfg.exclude_scifact
            layer = self.layers[s["layer"]] if s["layer"] else None
            use_structured = use_docs = True
            if s["router"]:
                rec["route"] = self.route(question)
                fin = rec["route"]["final"]
                use_structured, use_docs = fin in ("structured", "hybrid"), fin in ("unstructured", "hybrid")
                if fin == "out_of_scope":
                    rec["answer"] = self.qa_cfg.abstention_message
                    rec.update(evidence=[], context_text="", structured_ids=[], doc_top10=[], doc_top10_chunks=[], prompt_blocks=[],
                               abstained=True, latency_s=round(time.perf_counter() - t0, 3), prompt_tokens=0, completion_tokens=0)
                    return rec
            structured, top10 = [], []
            if use_structured:
                structured = self.pipeline.structured.search(question)
                rec["structured_status"] = self.pipeline.structured.last_status
            if use_docs:
                top10 = self.pipeline.unstructured.search(question, faiss_top_k=10, rerank_top_k=10, semantic=layer)
            unstructured = top10[:RERANK_TOP_K]            # the E14 default: 5 documents' chunks reach fusion
            fused = reciprocal_rank_fusion(structured, unstructured)
            context = build_context(fused, top_n=DEFAULT_TOP_N, per_source_budget=cfg.per_source_budget)
            gen = generate_answer(question, context["context_text"], client=self.client)
            rec["answer"] = gen["answer"]
            rec["abstained"] = not context["context_text"].strip()
            rec["structured_ids"] = [str(r["record_id"]) for r in structured]
            rec["doc_top10_chunks"] = [r["record_id"] for r in top10]
            docs: list[str] = []
            for r in top10:
                d = (r.get("metadata") or {}).get("provenance", {}).get("document_id") or r["record_id"]
                if d not in docs:
                    docs.append(d)
            rec["doc_top10"] = docs
            rec["evidence"] = [{"id": e["id"], "source": e["source"], "dataset": e["dataset"], "record_id": e["record_id"],
                                "label": e["provenance_label"], "content": e["content"], "metadata": e.get("metadata", {}),
                                "semantic_added": bool((e.get("metadata") or {}).get("semantic_added"))} for e in context["evidence"]]
            rec["context_text"] = context["context_text"]
            rec["prompt_blocks"] = [{"id": e["id"], "source": e["source"], "doc_id": (e.get("metadata") or {}).get("provenance", {}).get("document_id"),
                                     "record_id": e["record_id"]} for e in context["evidence"]]
            added = [r["record_id"] for r in top10 if (r.get("metadata") or {}).get("semantic_added")]
            first = next((r for r in top10 if (r.get("metadata") or {}).get("semantic")), None)
            rec["semantic"] = None if layer is None else {"added_chunks": added, **((first or {}).get("metadata", {}).get("semantic", {}) or {})}
        rec["latency_s"] = round(time.perf_counter() - t0, 3)
        rec["prompt_tokens"], rec["completion_tokens"] = self.client.prompt_tokens, self.client.completion_tokens
        return rec


# ---------------------------------------------------------------------------------------------------------------------------------
# judging
# ---------------------------------------------------------------------------------------------------------------------------------
FACT_TEMPLATE = """Decide whether the ANSWER explicitly states the FACT. A paraphrase counts; a vague or related statement does not.
Do NOT use outside knowledge and do NOT judge whether the fact is true in general.

QUESTION:
{question}

FACT:
{fact}

ANSWER:
{answer}

Output ONLY this JSON:
{{"present": 0|1, "reason": "<one short sentence>"}}
"""


class CachedJudge:
    """The E14a judge (same model, temperature 0, seed 42, same prompts). Identical prompts are answered from results/perf_report/judge_cache.jsonl
    (decoding is deterministic, verified in the report); `uncached=True` bypasses it for the integrity re-judge."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.client = OllamaClient(model=model)
        self.model = model
        self.cache = {r["key"]: r["raw"] for r in read_jsonl(JUDGE_CACHE)} if model == DEFAULT_MODEL else {}
        self.calls = self.hits = 0

    def chat(self, system: str, user: str, uncached: bool = False) -> str:
        key = hashlib.sha1((self.model + "\x00" + system + "\x00" + user).encode("utf-8")).hexdigest()
        if not uncached and key in self.cache:
            self.hits += 1
            return self.cache[key]
        raw = self.client.chat(system=system, user=user)
        self.calls += 1
        if not uncached and self.model == DEFAULT_MODEL:
            self.cache[key] = raw
            append_jsonl(JUDGE_CACHE, {"key": key, "raw": raw})
        return raw


def num_in(anchor: str, text: str) -> bool:
    if anchor.lower() in text.lower():
        return True
    na = cit.numbers_in(anchor)
    return bool(na) and na <= cit.numbers_in(text)


def reference_text(q: dict) -> str:
    """Reference evidence shown to the judge (E14a: the known-relevant chunk / the SQL ground truth)."""
    ref = q["reference"]
    if ref["kind"] == "sql_record":
        return json.dumps(q.get("gold_sql"), default=str)
    if ref["kind"] == "document_ids":
        return e14._reference_chunk_text(ref["expected_document_ids"])
    parts = [f"REFERENCE ANSWER: {ref.get('reference_answer', '')}"]
    sql = [f["sql"] for f in q["gold_facts"] if f.get("sql")]
    if sql:
        parts.append("DATABASE FACTS: " + json.dumps(sql, default=str))
    for doc in ref.get("expected_document_ids", []):
        text = e14._reference_chunk_text([doc], max_chars=1800)
        phrases = (ref.get("must_contain") or {}).get(doc, [])
        if phrases:
            from build_questions import _doc_text
            full = _doc_text(doc)
            low = full.lower()
            windows = [full[max(0, low.find(p.lower()) - 350): low.find(p.lower()) + 450] for p in phrases if low.find(p.lower()) >= 0]
            text = " ... ".join(windows) or text
        parts.append(f"DOCUMENT {doc}: {text[:1800]}")
    return "\n".join(parts)


def score_answer(q: dict, rec: dict, judge: CachedJudge) -> dict:
    """Correctness / relevance / groundedness / hallucination for one answer, using the E14a definitions (see module docstring of
    base_vs_rag) and, for cross/multi questions, per-fact scoring."""
    question, answer, arm = q["query"], rec["answer"], rec["arm"]
    ref_text = reference_text(q)
    out = {"arm": arm, "id": q["id"], "run": rec["run"], "category": q["category"], "is_core": q["is_core"]}

    # relevance (and, for documents, correctness) come from the E14a correctness judge
    cj = e14._parse_judge_json(judge.chat(e14.JUDGE_SYSTEM, e14.CORRECTNESS_TEMPLATE.format(
        question=question, reference=ref_text if ref_text.strip() else "(no reference evidence text available)", answer=answer)))
    out["relevance"], out["judge_correctness"] = cj.get("relevance"), cj.get("correctness")
    out["judge_parse_error"] = "_parse_error" in cj

    kind = q["reference"]["kind"]
    facts_detail = []
    if kind == "sql_record":
        det = e14.score_structured_correctness(answer, q["gold_sql"], question)
        out["correctness"], out["correctness_method"] = det["correctness"], det["method"]
        out["correctness_detail"] = {k: v for k, v in det.items() if k in ("discriminative_pks", "pks_found", "value_anchors", "value_anchors_found", "anchor")}
    elif kind == "document_ids":
        out["correctness"], out["correctness_method"] = cj.get("correctness"), "llm_judged_vs_reference (E14a judge)"
    else:                                                    # cross / multi: every scorable gold fact must be present
        for f in q["gold_facts"]:
            if f["kind"] == "sql" or (f["kind"] == "doc" and f["anchors"]):
                anchors = [a for a in f["anchors"] if a.lower() not in question.lower()]   # question-echoed anchors prove nothing
                if not anchors:
                    continue
                facts_detail.append({"fact": f["text"], "method": "deterministic anchors", "present": all(num_in(a, answer) for a in anchors)})
            elif f["kind"] == "doc":
                fj = e14._parse_judge_json(judge.chat(e14.JUDGE_SYSTEM, FACT_TEMPLATE.format(question=question, fact=f["text"], answer=answer)))
                facts_detail.append({"fact": f["text"], "method": "llm judge per fact", "present": fj.get("present") == 1,
                                     "parse_error": "_parse_error" in fj})
            else:                                           # doc_policy: the E14a correctness judge against the gold documents
                facts_detail.append({"fact": f["text"], "method": "E14a judge vs gold documents", "present": cj.get("correctness") == 2})
        n = len(facts_detail)
        k = sum(x["present"] for x in facts_detail)
        out["correctness"] = None if n == 0 else (2 if k == n else (1 if k else 0))
        out["correctness_method"] = "all gold facts present (per fact)"
        out["facts"] = facts_detail

    # hallucination against the reference evidence (all arms; E14a base-condition basis) and against the context (RAG arms)
    gref = e14._parse_judge_json(judge.chat(e14.JUDGE_SYSTEM, e14.GROUNDING_TEMPLATE.format(
        question=question, context=ref_text if ref_text.strip() else "(none)", answer=answer)))
    out["halluc_ref"] = gref.get("hallucination")
    if arm == "A" or rec.get("abstained"):
        out["groundedness"], out["halluc_ctx"] = None, None
    else:
        gctx = e14._parse_judge_json(judge.chat(e14.JUDGE_SYSTEM, e14.GROUNDING_TEMPLATE.format(
            question=question, context=rec["context_text"] if rec["context_text"].strip() else "(no context was provided to the answerer)", answer=answer)))
        out["groundedness"], out["halluc_ctx"] = gctx.get("groundedness"), gctx.get("hallucination")
        out["judge_parse_error"] = out["judge_parse_error"] or ("_parse_error" in gctx)
    out["judge_parse_error"] = out["judge_parse_error"] or ("_parse_error" in gref)
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# citation verification (project verifier)
# ---------------------------------------------------------------------------------------------------------------------------------
def _verifier_items(evidence: list[dict]) -> dict:
    items = {}
    for e in evidence:
        md = dict(e.get("metadata") or {})
        md.update(evidence_id=e["id"])
        if e["source"] == "structured":
            row = {k: v for k, v in (e.get("metadata") or {}).items()}
            md.update(table_name=e["dataset"], row_id=e["record_id"], columns_used=sorted(row.keys()))
        items[e["id"]] = {"source": e["source"], "dataset": e["dataset"], "content": e["content"], "metadata": md,
                          "retrieval_method": "exact_filter" if e["source"] == "structured" else "hybrid_rerank"}
    return items


_ABSTAIN_MARKERS = e14.ABSTENTION_MARKERS


def citation_check(rec: dict, cfg: QAConfig) -> dict:
    """Sentence-level citation verification of an E14-format answer with integration.qa.citations (numbers + lexical overlap + NLI)."""
    answer = rec["answer"]
    if rec.get("abstained") or any(m in answer.lower() for m in _ABSTAIN_MARKERS):
        return {"checked": False, "reason": "abstention-like answer", "n_sentences": 0}
    items = _verifier_items(rec["evidence"])
    parsed = cit.parse_answer(answer, set(items))
    if parsed.get("insufficient") or not parsed["sentences"]:
        return {"checked": False, "reason": "no sentences", "n_sentences": 0}
    verified = cit.verify_answer(parsed, items, cfg)
    n = len(verified)
    with_cit = [s for s in verified if s["citations"]]
    return {"checked": True, "n_sentences": n, "n_cited": len(with_cit),
            "n_supported": sum(s["support_status"] == "SUPPORTED" for s in verified),
            "n_weak": sum(s["support_status"] == "WEAK" for s in verified),
            "n_unsupported": sum(s["support_status"] == "UNSUPPORTED" for s in verified),
            "n_cited_supported": sum(s["support_status"] == "SUPPORTED" for s in with_cit),
            "n_invalid_citation_ids": sum(len(s.get("invalid_citations", [])) for s in verified),
            "sentences": [{"text": s["text"][:200], "citations": s["citations"], "status": s["support_status"]} for s in verified]}


def pct(num: float, den: float) -> float | None:
    return None if not den else round(100.0 * num / den, 1)


def pct_of_two(vals) -> float | None:
    v = [x for x in vals if isinstance(x, (int, float))]
    return round(sum(v) / (2 * len(v)) * 100, 1) if v else None


def rate_pct(vals) -> float | None:
    v = [x for x in vals if isinstance(x, (int, float))]
    return round(sum(v) / len(v) * 100, 1) if v else None


def p95(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], 2)
