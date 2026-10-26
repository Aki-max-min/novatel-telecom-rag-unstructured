"""
Base-LLM vs RAG benchmark for NovaTel E14.

Deliberately lean and crash-safe, replacing the earlier monolithic harness
that held generation + DeepEval judge + reranker + NLI models resident at
once (~5 model calls/query, no checkpointing) and thrashed for hours.

Design:
  * Three SEQUENTIAL stages, run as separate processes. No two heavy models
    are ever resident together.
      Stage A (generate): Ollama + retrieval models only. -> answers.jsonl
      Stage B (score):    Ollama judge + SQLite only.     -> scores.jsonl
      Stage C (aggregate): no models at all.              -> benchmark_results.json
  * Every stage appends to its .jsonl and flushes after each query, and skips
    query_ids already present on restart. A crash loses at most one query.

Scoring rubric (0/1/2), deterministic anchors preferred:
  Correctness    0 wrong / 1 partial / 2 fully correct
  Relevance      0 off-topic / 1 partially on-topic / 2 directly answers
  Groundedness   0/1/2  -- RAG ONLY (base has no retrieved context)
  Hallucination  0 none / 1 at least one unsupported factual claim

Which scores are deterministic vs LLM-judged:
  * STRUCTURED queries -> Correctness is DETERMINISTIC: the ground-truth fact
    is read straight from the SQLite DB via StructuredRetriever and matched
    against the answer text (see score_structured_correctness for the exact
    anchor rule). Groundedness for structured RAG answers is also
    deterministic, via factcheck.check_structured_claims.
  * DOCUMENT queries (synthetic + public TRAI) -> Correctness, Relevance,
    Groundedness and Hallucination are LLM-JUDGED by the local Ollama model
    at temperature 0, with the KNOWN-RELEVANT chunk passed in as reference
    evidence. These MUST be human spot-checked; a local 7B judge is a signal,
    not ground truth.
  * Relevance and Hallucination for structured queries are also LLM-judged.

Nothing here invents a gold answer: reference evidence is always an existing
expected_document_ids / relevant_documents entry from the repo's own eval
files, or a row actually present in the SQLite DB.
"""

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "experiments" / "benchmark_base_vs_rag"

QUERYSET_PATH = OUT_DIR / "queryset.json"
ANSWERS_PATH = OUT_DIR / "answers.jsonl"
SCORES_PATH = OUT_DIR / "scores.jsonl"
RESULTS_PATH = OUT_DIR / "benchmark_results.json"

SYNTHETIC_EVAL_PATH = PROJECT_ROOT / "data" / "vectorstore" / "retrieval_evaluation.json"
PUBLIC_QUERIES_PATH = PROJECT_ROOT / "data" / "experiments" / "public_pdfs" / "public_pdf_queries.json"
STRUCTURED_BENCHMARK_PATH = PROJECT_ROOT / "structured" / "benchmark.json"
SUBSET_RUN_PATH = PROJECT_ROOT / "data" / "experiments" / "integrated_rag" / "20261013T183747Z_E14-subset.json"

SYNTHETIC_CHUNK_DIR = PROJECT_ROOT / "data" / "processed" / "chunks"
PUBLIC_CHUNK_METADATA = PROJECT_ROOT / "data" / "experiments" / "public_pdfs" / "vectorstore" / "chunk_metadata_enriched.json"

NA = "not available"

# Curated selection, by source query_id. Chosen to span distinct tables /
# categories / source PDFs -- and deliberately to INCLUDE public TRAI queries,
# which the earlier 10-query subset had zero of.
STRUCTURED_IDS = ["S01", "S03", "S04", "S06", "S07", "S09", "S12", "S15"]
SYNTHETIC_IDS = ["Q01", "Q04", "Q08", "Q13", "Q17", "Q20", "Q25", "Q28"]
PUBLIC_IDS = ["RW_001", "RW_004", "RW_007", "RW_010", "RW_017", "RW_023"]

BASE_SYSTEM_PROMPT = (
    "You are NovaTel's customer support assistant. Answer the customer's "
    "question as accurately and helpfully as you can."
)

# Used ONLY to score the S15 negative control (abstention_expected), so
# broadening it cannot affect any other query's score. Extended after the
# first run showed both variants refusing in phrasings none of the original
# markers caught ("I didn't understand the query...", "The question is not
# provided...") -- those are correct abstentions and must score 2.
ABSTENTION_MARKERS = (
    "don't have enough", "do not have enough", "abstain", "cannot answer",
    "can't answer", "not enough information", "no information", "unable to answer",
    "insufficient evidence", "insufficient information", "does not contain",
    "doesn't contain", "cannot provide", "can't provide", "not clear what",
    "unclear", "gibberish", "does not appear to be a valid",
    "didn't understand", "did not understand", "don't understand",
    "rephrase", "clarify your question", "question is not provided",
    "no question", "without a specific question", "not a valid question",
    "could you please provide", "need it to be clearly stated",
)


def _load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# PART 1 -- curated query set
# ---------------------------------------------------------------------------

def build_queryset() -> dict:
    """Reuses existing eval queries only. Records, per query, where it came
    from and what its pre-existing reference evidence is."""
    structured = {r["id"]: r for r in _load_json(STRUCTURED_BENCHMARK_PATH)}
    synthetic = {r["question_id"]: r for r in _load_json(SYNTHETIC_EVAL_PATH)["results"]}
    public = {r["query_id"]: r for r in _load_json(PUBLIC_QUERIES_PATH)}

    queries = []

    for qid in STRUCTURED_IDS:
        row = structured[qid]
        queries.append({
            "query_id": qid,
            "question": row["question"],
            "intended_category": "structured",
            "source_file": str(STRUCTURED_BENCHMARK_PATH.relative_to(PROJECT_ROOT)),
            "reference_evidence": {
                "kind": "sql_record",
                "expected_table": row["expected_table"],
                "expected_method": row["expected_method"],
                "expected_filter_column": row.get("expected_filter_column"),
                "expected_filter_value": row.get("expected_filter_value"),
                "benchmark_query_type": row["query_type"],
            },
        })

    for qid in SYNTHETIC_IDS:
        row = synthetic[qid]
        queries.append({
            "query_id": qid,
            "question": row["question"],
            "intended_category": "unstructured_synthetic",
            "source_file": str(SYNTHETIC_EVAL_PATH.relative_to(PROJECT_ROOT)),
            "reference_evidence": {
                "kind": "document_ids",
                "expected_document_ids": row["expected_document_ids"],
                "category": row["category"],
            },
        })

    for qid in PUBLIC_IDS:
        row = public[qid]
        queries.append({
            "query_id": qid,
            "question": row["query"],
            "intended_category": "unstructured_public",
            "source_file": str(PUBLIC_QUERIES_PATH.relative_to(PROJECT_ROOT)),
            "reference_evidence": {
                "kind": "document_ids",
                "expected_document_ids": row["relevant_documents"],
            },
        })

    # Interleave the three categories round-robin so that (a) the first few
    # queries exercise all three scoring paths, and (b) a crash mid-run
    # leaves a category-balanced partial set rather than all-structured.
    buckets: dict[str, list[dict]] = {}
    for q in queries:
        buckets.setdefault(q["intended_category"], []).append(q)
    order = ["structured", "unstructured_synthetic", "unstructured_public"]
    interleaved = []
    i = 0
    while any(buckets.get(c) for c in order):
        category = order[i % len(order)]
        if buckets.get(category):
            interleaved.append(buckets[category].pop(0))
        i += 1
    queries = interleaved

    composition: dict[str, int] = {}
    for q in queries:
        composition[q["intended_category"]] = composition.get(q["intended_category"], 0) + 1

    return {
        "description": "Curated Base-vs-RAG benchmark query set. Every query is REUSED "
                       "from an existing NovaTel eval file; none were written for this run. "
                       "'intended_category' is the query's source/intent. The runtime "
                       "structured/unstructured/hybrid classification is recorded separately "
                       "in answers.jsonl as 'observed_query_type', because hybrid is only "
                       "observable after retrieval runs. Queries are interleaved across the "
                       "three categories so partial runs stay category-balanced.",
        "n_queries": len(queries),
        "composition": composition,
        "queries": queries,
    }


# ---------------------------------------------------------------------------
# Reference chunk text (for passing known-relevant evidence to the judge)
# ---------------------------------------------------------------------------

_public_text_by_doc = None


def _reference_chunk_text(expected_document_ids: list[str], max_chars: int = 2000) -> str:
    """Best-effort: pull the text of the first known-relevant document so the
    judge has the reference evidence in front of it. Returns "" if the text
    cannot be located -- never invents text."""
    global _public_text_by_doc

    for doc_id in expected_document_ids:
        # synthetic corpus: chunk files on disk
        chunk_path = SYNTHETIC_CHUNK_DIR / f"{doc_id}_chunk_000.json"
        if chunk_path.exists():
            text = _load_json(chunk_path).get("text", "")
            if text:
                return text[:max_chars]

        # public corpus: text lives inline in the enriched metadata
        if doc_id.startswith("PUBLIC_PDF"):
            if _public_text_by_doc is None:
                _public_text_by_doc = {}
                for record in _load_json(PUBLIC_CHUNK_METADATA):
                    did = record.get("document_id")
                    if did and did not in _public_text_by_doc and record.get("text"):
                        _public_text_by_doc[did] = record["text"]
            if doc_id in _public_text_by_doc:
                return _public_text_by_doc[doc_id][:max_chars]

    return ""


# ---------------------------------------------------------------------------
# PART 2 -- Stage A: generation (base + RAG), incremental
# ---------------------------------------------------------------------------

def _done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["query_id"])
                except Exception:
                    continue
    return done


def _cached_rag_answers() -> dict[str, str]:
    """RAG answers already generated by the earlier subset run -- reused so we
    don't pay for the same generation twice. The subset run predates evidence
    persistence, so evidence is re-derived by retrieval (no LLM) instead."""
    if not SUBSET_RUN_PATH.exists():
        return {}
    try:
        old = _load_json(SUBSET_RUN_PATH)
        return {r["query_id"]: r["answer"] for r in old.get("per_query_records", [])}
    except Exception:
        return {}


def stage_a_generate(limit: int | None = None) -> None:
    """Loads the Ollama client + retrieval models ONCE, then for each query
    generates a BASE answer (no retrieval) and a RAG answer (full pipeline).
    Appends each result to answers.jsonl immediately."""
    from integration.rag.pipeline import RagPipeline

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    queryset = _load_json(QUERYSET_PATH)
    queries = queryset["queries"][:limit] if limit else queryset["queries"]

    already = _done_ids(ANSWERS_PATH)
    cached_rag = _cached_rag_answers()

    pipeline = RagPipeline()
    total = len(queries)
    try:
        for index, query in enumerate(queries, start=1):
            qid = query["query_id"]
            if qid in already:
                print(f"query {index}/{total} ({qid}) already done -- skipping", flush=True)
                continue

            question = query["question"]
            started = time.perf_counter()

            # (a) BASE: same model, temp 0, NO retrieval and NO context.
            base_answer = pipeline.llm_client.chat(system=BASE_SYSTEM_PROMPT, user=question)
            base_elapsed = time.perf_counter() - started

            # (b) RAG: full pipeline. Reuse a cached answer when one exists,
            # but still re-derive evidence via retrieval (no LLM) so
            # groundedness can be scored.
            rag_started = time.perf_counter()
            structured_results = pipeline.structured.search(question)
            unstructured_results = pipeline.unstructured.search(question)

            from integration.rag.context_builder import DEFAULT_TOP_N, build_context
            from integration.rag.fuse import reciprocal_rank_fusion

            fused = reciprocal_rank_fusion(structured_results, unstructured_results)
            context = build_context(fused, top_n=DEFAULT_TOP_N)

            reused = qid in cached_rag
            if reused:
                rag_answer = cached_rag[qid]
            else:
                from integration.rag.generate import generate_answer
                rag_answer = generate_answer(question, context["context_text"], client=pipeline.llm_client)["answer"]
            rag_elapsed = time.perf_counter() - rag_started

            if structured_results and unstructured_results:
                observed = "hybrid"
            elif structured_results:
                observed = "structured"
            elif unstructured_results:
                observed = "unstructured"
            else:
                observed = "no_retrieval_results"

            record = {
                "query_id": qid,
                "question": question,
                "intended_category": query["intended_category"],
                "observed_query_type": observed,
                "reference_evidence": query["reference_evidence"],
                "base_answer": base_answer,
                "rag_answer": rag_answer,
                "rag_answer_reused_from_subset_run": reused,
                "rag_evidence": [
                    {
                        "id": e["id"],
                        "source": e["source"],
                        "dataset": e["dataset"],
                        "record_id": e["record_id"],
                        "provenance_label": e["provenance_label"],
                        "content": e["content"],
                        "metadata": e.get("metadata", {}),
                    }
                    for e in context["evidence"]
                ],
                "n_structured_results": len(structured_results),
                "n_unstructured_results": len(unstructured_results),
                "base_latency_sec": round(base_elapsed, 2),
                "rag_latency_sec": round(rag_elapsed, 2),
            }

            with open(ANSWERS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                f.flush()

            print(f"query {index}/{total} ({qid}) done "
                  f"[observed={observed}, rag_reused={reused}, "
                  f"base={base_elapsed:.1f}s rag={rag_elapsed:.1f}s]", flush=True)
    finally:
        pipeline.close()


# ---------------------------------------------------------------------------
# PART 3 -- Stage B: scoring
# ---------------------------------------------------------------------------

def _sql_ground_truth(reference: dict) -> dict:
    """Reads the ground-truth fact for a structured query straight from the
    SQLite DB, via StructuredRetriever (read-only). Returns the deterministic
    anchor tokens the answer is expected to contain."""
    sys.path.insert(0, str(PROJECT_ROOT / "structured"))
    from retriever import StructuredRetriever  # noqa: E402

    table = reference.get("expected_table")
    if not table:
        return {"kind": "abstention_expected", "anchors": []}

    retriever = StructuredRetriever()
    try:
        method = reference.get("expected_method")
        column = reference.get("expected_filter_column")
        value = reference.get("expected_filter_value")

        if method == "aggregate":
            res = retriever.aggregate_count(table, column, value)
            count = res["results"][0]["metadata"]["count"]
            return {"kind": "aggregate_count", "anchors": [str(count)], "count": count}

        if column is not None:
            res = retriever.exact_filter(table, column, value, top_k=5)
        else:
            res = retriever.search(reference_question_placeholder := "", top_k=5)  # not used
        rows = res["results"]
        if not rows:
            return {"kind": "no_rows", "anchors": []}

        schema_pk_anchors = [r["record_id"] for r in rows if r.get("record_id")]
        status_anchors = []
        for r in rows:
            md = r.get("metadata", {}) or {}
            for key in ("status", "payment_status", "activation_status", "kyc_status"):
                if key in md and md[key] is not None:
                    status_anchors.append(str(md[key]))
        return {
            "kind": "rows",
            "anchors": schema_pk_anchors,
            "status_anchors": sorted(set(status_anchors)),
            "n_rows": len(rows),
        }
    finally:
        retriever.close()


def _looks_like_abstention(answer: str) -> bool:
    low = answer.lower()
    return any(marker in low for marker in ABSTENTION_MARKERS)


def score_structured_correctness(answer: str, ground_truth: dict, question: str = "") -> dict:
    """
    DETERMINISTIC. Anchor rules (documented so the score is auditable):
      * aggregate            -> 2 if the exact count string appears, else 0
      * rows (filter/lookup) -> anchors are first filtered to DISCRIMINATIVE
        ones: any anchor whose string already appears in the QUESTION is
        dropped, because an answer echoing an identifier from the question
        (e.g. "customer 1001") proves nothing about correctness. Then:
          - if discriminative PKs remain: 2 = all present, 1 = some, 0 = none
          - else if value anchors (status-like fields) remain: 2 = any
            present, 0 = none
          - else: None (not deterministically scorable)
      * abstention_expected  -> 2 if the answer abstains, else 0
    """
    low = answer.lower()
    q_low = (question or "").lower()
    kind = ground_truth["kind"]

    if kind == "abstention_expected":
        return {"correctness": 2 if _looks_like_abstention(answer) else 0,
                "method": "deterministic:abstention_expected"}

    if kind == "aggregate_count":
        hit = ground_truth["anchors"][0] in answer.replace(",", "")
        return {"correctness": 2 if hit else 0,
                "method": "deterministic:aggregate_count",
                "anchor": ground_truth["anchors"][0]}

    if kind == "rows":
        all_pks = [str(pk) for pk in ground_truth["anchors"] if pk]
        all_values = [str(v) for v in ground_truth.get("status_anchors", []) if v]

        # Drop anchors the question already contains -- non-discriminative.
        pks = [pk for pk in all_pks if pk.lower() not in q_low]
        values = [v for v in all_values if v.lower() not in q_low]

        pks_found = [pk for pk in pks if pk in answer]
        values_found = [v for v in values if v.lower() in low]

        if pks:
            score = 2 if len(pks_found) == len(pks) else (1 if pks_found else 0)
            basis = "discriminative_pks"
        elif values:
            score = 2 if values_found else 0
            basis = "value_anchors"
        else:
            score = None
            basis = "no_discriminative_anchors"

        return {"correctness": score,
                "method": f"deterministic:row_anchors:{basis}",
                "all_pks": all_pks,
                "discriminative_pks": pks,
                "pks_found": pks_found,
                "value_anchors": values,
                "value_anchors_found": values_found,
                "dropped_as_question_echoed": [a for a in all_pks + all_values
                                               if a.lower() in q_low]}

    return {"correctness": None, "method": "deterministic:no_rows_in_db"}


JUDGE_SYSTEM = (
    "You are a strict evaluation judge for a telecom support assistant. "
    "You output ONLY a single JSON object, no prose, no markdown fences."
)

# Judge call 1 -- CORRECTNESS + RELEVANCE, scored against the REFERENCE
# evidence (the known-relevant chunk / SQL record), i.e. "is this the right
# answer to the question?"
CORRECTNESS_TEMPLATE = """Score the ANSWER against the QUESTION and the REFERENCE EVIDENCE.

QUESTION:
{question}

REFERENCE EVIDENCE (the known-correct source material for this question; may be partial):
{reference}

ANSWER TO SCORE:
{answer}

Output ONLY this JSON:
{{"correctness": 0|1|2, "relevance": 0|1|2, "reason": "<one short sentence>"}}

correctness: 0 = wrong/contradicts the reference, 1 = partially correct or incomplete, 2 = fully correct per the reference
relevance: 0 = off-topic, 1 = partially on-topic, 2 = directly answers the question
"""

# Judge call 2 -- GROUNDEDNESS + HALLUCINATION, scored STRICTLY against the
# context that was actually shown to the generator. Factual correctness is
# explicitly out of scope here, so a faithful summary of the WRONG document
# still scores as grounded (that is a retrieval failure, not a hallucination).
GROUNDING_TEMPLATE = """Assess ONLY whether each claim in the ANSWER is supported by the CONTEXT shown below.

Do NOT consider whether the answer is factually correct for the question. Do NOT
use outside knowledge. An answer that faithfully restates the CONTEXT is fully
grounded even if the CONTEXT is not the ideal source for the question.

QUESTION (for reference only -- do not score correctness):
{question}

CONTEXT THAT WAS SHOWN TO THE ANSWERER:
{context}

ANSWER TO ASSESS:
{answer}

Output ONLY this JSON:
{{"groundedness": 0|1|2, "hallucination": 0|1, "reason": "<one short sentence>"}}

groundedness: 0 = claims are not supported by the context, 1 = partially supported, 2 = every claim is supported by the context
hallucination: 1 if the answer states at least one factual claim that is NOT supported by the context, else 0
"""


def _judge_correctness(client, question: str, reference: str, answer: str) -> dict:
    prompt = CORRECTNESS_TEMPLATE.format(
        question=question,
        reference=reference if reference.strip() else "(no reference evidence text available)",
        answer=answer,
    )
    return _parse_judge_json(client.chat(system=JUDGE_SYSTEM, user=prompt))


def _judge_grounding(client, question: str, context: str, answer: str) -> dict:
    prompt = GROUNDING_TEMPLATE.format(
        question=question,
        context=context if context.strip() else "(no context was provided to the answerer)",
        answer=answer,
    )
    return _parse_judge_json(client.chat(system=JUDGE_SYSTEM, user=prompt))


def _parse_judge_json(raw: str) -> dict:
    """Tolerant JSON extraction -- a local 7B judge sometimes wraps output in
    fences or adds a stray sentence. Returns {"_parse_error": raw} on failure
    rather than guessing a score."""
    text = raw.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {"_parse_error": raw[:400]}
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return {"_parse_error": raw[:400]}


def reference_retrieved(record: dict) -> dict:
    """
    DETERMINISTIC: did retrieval actually surface the known-relevant
    chunk/record? This is the signal that separates a retrieval failure from
    a generation failure -- it uses ground truth, never a judge.
    """
    reference = record["reference_evidence"]
    evidence = record["rag_evidence"]

    if reference["kind"] == "document_ids":
        expected = set(reference["expected_document_ids"])
        retrieved_docs = []
        for e in evidence:
            if e["source"] != "unstructured":
                continue
            doc_id = (e.get("metadata") or {}).get("provenance", {}).get("document_id") or e["record_id"]
            if doc_id not in retrieved_docs:
                retrieved_docs.append(doc_id)
        return {
            "retrieved_ok": bool(expected & set(retrieved_docs)),
            "basis": "expected_document_id present in retrieved unstructured evidence",
            "expected": sorted(expected),
            "retrieved_doc_ids": retrieved_docs,
        }

    table = reference.get("expected_table")
    if not table:
        # S15 negative control: there is nothing relevant to retrieve, so
        # retrieval cannot be at fault -- any failure here is the generator
        # declining to abstain.
        return {
            "retrieved_ok": True,
            "basis": "negative control -- no relevant record exists; retrieval not at fault",
        }

    datasets = [e["dataset"] for e in evidence if e["source"] == "structured"]
    return {
        "retrieved_ok": table in datasets,
        "basis": "expected_table present among retrieved structured evidence datasets",
        "expected_table": table,
        "retrieved_datasets": sorted(set(datasets)),
    }


def derive_failure_type(correctness, retrieved_ok: bool, groundedness, hallucination) -> dict:
    """
    Derived from three signals: (1) was the known-relevant chunk/record
    retrieved [DETERMINISTIC], (2) is the answer grounded in the context it
    was given, (3) is the answer correct.

      correctness == 2                      -> "correct"
      not retrieved  and not grounded       -> "both"
      not retrieved  and grounded           -> "retrieval_failure"
                                               (faithful to the wrong source)
      retrieved      and (any)              -> "generation_failure"
                                               (right evidence available, wrong output)

    correctness is None (not deterministically scorable) -> "not_available".
    """
    if correctness is None:
        return {"failure_type": "not_available", "reason": "correctness not scorable"}

    if correctness == 2:
        return {"failure_type": "correct", "reason": "correctness == 2"}

    grounded_ok = (groundedness is not None and groundedness >= 1) and (hallucination == 0)

    if not retrieved_ok and not grounded_ok:
        failure = "both"
    elif not retrieved_ok:
        failure = "retrieval_failure"
    else:
        failure = "generation_failure"

    return {
        "failure_type": failure,
        "reason": f"correctness={correctness}, retrieved_ok={retrieved_ok}, "
                  f"groundedness={groundedness}, hallucination={hallucination}",
    }


def stage_b_score(limit: int | None = None) -> None:
    """Loads ONLY the Ollama judge client + SQLite. No embedding/reranker/NLI
    models. Appends each score record to scores.jsonl immediately."""
    from integration.eval.factcheck import check_structured_claims
    from integration.rag.llm_client import OllamaClient

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    answers = [json.loads(line) for line in ANSWERS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit:
        answers = answers[:limit]

    already = _done_ids(SCORES_PATH)
    client = OllamaClient()
    total = len(answers)

    for index, record in enumerate(answers, start=1):
        qid = record["query_id"]
        if qid in already:
            print(f"score {index}/{total} ({qid}) already done -- skipping", flush=True)
            continue

        reference = record["reference_evidence"]
        is_structured = reference["kind"] == "sql_record"

        if is_structured:
            ground_truth = _sql_ground_truth(reference)
            reference_text = json.dumps(ground_truth, default=str)
            base_correct = score_structured_correctness(record["base_answer"], ground_truth, record["question"])
            rag_correct = score_structured_correctness(record["rag_answer"], ground_truth, record["question"])
        else:
            ground_truth = None
            reference_text = _reference_chunk_text(reference.get("expected_document_ids", []))
            base_correct = None
            rag_correct = None

        rag_context_text = "\n\n".join(
            f"[{e['id']}] {e['content']}" for e in record["rag_evidence"]
        )

        # Judge call 1 (both variants): CORRECTNESS + RELEVANCE vs REFERENCE.
        base_correctness_judge = _judge_correctness(client, record["question"], reference_text, record["base_answer"])
        rag_correctness_judge = _judge_correctness(client, record["question"], reference_text, record["rag_answer"])

        # Judge call 2: GROUNDEDNESS + HALLUCINATION vs the context actually
        # shown to the generator. The base condition has NO retrieved context,
        # so its hallucination is necessarily assessed against the reference
        # evidence instead -- a DIFFERENT basis, recorded explicitly below and
        # flagged in the report. Base groundedness stays None by definition.
        rag_grounding_judge = _judge_grounding(client, record["question"], rag_context_text, record["rag_answer"])
        base_grounding_judge = _judge_grounding(client, record["question"], reference_text, record["base_answer"])

        # Deterministic structured-citation check for the RAG answer
        rag_factcheck = check_structured_claims(record["rag_answer"], record["rag_evidence"])

        retrieval_check = reference_retrieved(record)

        base_correctness = (base_correct or {}).get("correctness") if is_structured else base_correctness_judge.get("correctness")
        rag_correctness = (rag_correct or {}).get("correctness") if is_structured else rag_correctness_judge.get("correctness")

        rag_failure = derive_failure_type(
            rag_correctness,
            retrieval_check["retrieved_ok"],
            rag_grounding_judge.get("groundedness"),
            rag_grounding_judge.get("hallucination"),
        )

        score_record = {
            "query_id": qid,
            "intended_category": record["intended_category"],
            "observed_query_type": record["observed_query_type"],
            "scoring_mode": "structured_deterministic+judge" if is_structured else "document_judge",
            "ground_truth": ground_truth,
            "reference_retrieved": retrieval_check,
            "failure_type": rag_failure["failure_type"],
            "failure_type_detail": rag_failure,
            "base": {
                "correctness": base_correctness,
                "correctness_method": (base_correct or {}).get("method") if is_structured else "llm_judged_vs_reference",
                "correctness_detail": base_correct,
                "relevance": base_correctness_judge.get("relevance"),
                "hallucination": base_grounding_judge.get("hallucination"),
                "hallucination_basis": "reference_evidence (base condition has no retrieved context)",
                "groundedness": None,  # base has no retrieved context by definition
                "outcome": "correct" if base_correctness == 2 else (
                    "incorrect" if base_correctness is not None else "not_available"),
                "judge_raw": {"correctness": base_correctness_judge, "grounding": base_grounding_judge},
            },
            "rag": {
                "correctness": rag_correctness,
                "correctness_method": (rag_correct or {}).get("method") if is_structured else "llm_judged_vs_reference",
                "correctness_detail": rag_correct,
                "relevance": rag_correctness_judge.get("relevance"),
                "hallucination": rag_grounding_judge.get("hallucination"),
                "hallucination_basis": "retrieved_context",
                "groundedness": rag_grounding_judge.get("groundedness"),
                "groundedness_basis": "retrieved_context",
                "judge_raw": {"correctness": rag_correctness_judge, "grounding": rag_grounding_judge},
                "factcheck": rag_factcheck,
            },
        }

        with open(SCORES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(score_record, ensure_ascii=False, default=str) + "\n")
            f.flush()

        print(f"score {index}/{total} ({qid}) done "
              f"[mode={score_record['scoring_mode']}, "
              f"base_correct={score_record['base']['correctness']}, "
              f"rag_correct={score_record['rag']['correctness']}, "
              f"retrieved_ok={retrieval_check['retrieved_ok']}, "
              f"failure={score_record['failure_type']}]", flush=True)


# ---------------------------------------------------------------------------
# PART 4 -- Stage C: aggregation
# ---------------------------------------------------------------------------

def _pct_of_two(values: list) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float))]
    return (sum(vals) / (2 * len(vals))) * 100 if vals else None


def _rate_pct(values: list) -> float | None:
    vals = [v for v in values if isinstance(v, (int, float))]
    return (sum(vals) / len(vals)) * 100 if vals else None


def _this_run_retrieval_precision(answers: list[dict]) -> dict:
    """Deterministic R@1/3/5 + MRR@10 for THIS run's document queries, from
    the RAG evidence actually retrieved vs the pre-existing reference
    document ids. No LLM."""
    doc_records = [a for a in answers if a["reference_evidence"]["kind"] == "document_ids"]
    k_values = (1, 3, 5)
    hits = {k: 0 for k in k_values}
    mrr_total = 0.0

    for record in doc_records:
        expected = set(record["reference_evidence"]["expected_document_ids"])
        retrieved = []
        for e in record["rag_evidence"]:
            if e["source"] != "unstructured":
                continue
            doc_id = (e.get("metadata", {}) or {}).get("provenance", {}).get("document_id") or e["record_id"]
            if doc_id not in retrieved:
                retrieved.append(doc_id)
        for k in k_values:
            if any(d in expected for d in retrieved[:k]):
                hits[k] += 1
        for rank, doc_id in enumerate(retrieved[:10], start=1):
            if doc_id in expected:
                mrr_total += 1.0 / rank
                break

    n = len(doc_records) or 1
    out = {f"R@{k}": hits[k] / n for k in k_values}
    out["MRR@10"] = mrr_total / n
    out["n_document_queries"] = len(doc_records)
    return out


def _preexisting_retrieval_precision() -> dict:
    """The repo's own standalone retrieval benchmarks, for context. Different
    (larger) query sets -- NOT the same sample as this run."""
    out = {}
    try:
        syn = _load_json(SYNTHETIC_EVAL_PATH)
        out["synthetic_29q"] = {
            "Top-1": syn["document_metrics"]["top1"],
            "Top-3": syn["document_metrics"]["top3"],
            "Top-5": syn["document_metrics"]["top5"],
            "MRR@10": NA + " (field absent in source file)",
            "source": str(SYNTHETIC_EVAL_PATH.relative_to(PROJECT_ROOT)),
        }
    except Exception:
        out["synthetic_29q"] = NA
    try:
        pub_path = PROJECT_ROOT / "data" / "experiments" / "public_pdfs" / "public_pdf_retrieval_evaluation.json"
        pub = _load_json(pub_path)
        out["public_30q"] = {**pub["metrics"], "source": str(pub_path.relative_to(PROJECT_ROOT))}
    except Exception:
        out["public_30q"] = NA
    return out


def _run_config(answers: list[dict]) -> dict:
    from integration.rag.context_builder import DEFAULT_TOP_N
    from integration.rag.fuse import RRF_K
    from integration.rag.llm_client import DEFAULT_MODEL
    from integration.rag.pipeline import EMBEDDING_MODEL_NAME

    quant = NA
    try:
        import ollama
        details = getattr(ollama.show(DEFAULT_MODEL), "details", None)
        quant = getattr(details, "quantization_level", None) or NA
    except Exception:
        pass

    composition: dict[str, int] = {}
    observed: dict[str, int] = {}
    for a in answers:
        composition[a["intended_category"]] = composition.get(a["intended_category"], 0) + 1
        observed[a["observed_query_type"]] = observed.get(a["observed_query_type"], 0) + 1

    return {
        "generation_model": DEFAULT_MODEL,
        "quantization": quant,
        "judge_model": f"ollama:{DEFAULT_MODEL} (local, temperature 0)",
        "base_condition": "same model, same temperature, NO retrieval and NO context",
        "rag_condition": "structured SQL + unstructured FAISS/metadata -> RRF -> top-N context -> same model",
        "embedding_model": EMBEDDING_MODEL_NAME,
        "fusion_method": "RRF",
        "rrf_k": RRF_K,
        "top_n_context": DEFAULT_TOP_N,
        "n_queries": len(answers),
        "query_counts_by_intended_category": composition,
        "query_counts_by_observed_type": observed,
        "scoring": {
            "structured_correctness": "DETERMINISTIC (SQLite ground-truth anchors; anchors echoed "
                                      "by the question are dropped as non-discriminative)",
            "negative_control_correctness": "DETERMINISTIC (correct abstention on S15 scores 2)",
            "reference_retrieved": "DETERMINISTIC (expected document_id / expected_table present in "
                                   "the retrieved evidence) -- this is what separates retrieval "
                                   "failure from generation failure",
            "structured_citation_factcheck": "DETERMINISTIC (exact-match of cited structured values)",
            "document_correctness_and_relevance": "LLM-judged vs the REFERENCE evidence "
                                                  "(known-relevant chunk), local model, temp 0",
            "groundedness_and_hallucination": "LLM-judged vs the RETRIEVED CONTEXT only; the judge is "
                                              "explicitly told not to consider factual correctness, so a "
                                              "faithful summary of the wrong document counts as grounded "
                                              "(that shows up as a retrieval_failure instead)",
            "base_hallucination_basis_asymmetry": "The base condition has NO retrieved context, so its "
                                                  "hallucination is assessed against the reference evidence "
                                                  "instead. Base vs RAG hallucination rates therefore rest "
                                                  "on different bases and are not strictly comparable; base "
                                                  "groundedness is left null by definition.",
            "failure_type": "DERIVED from reference_retrieved (deterministic) x groundedness x correctness",
            "caveat": "Document-side rubric scores are judged by a local 7B model and MUST be "
                      "human spot-checked. Structured correctness, reference_retrieved and the "
                      "citation factcheck are deterministic.",
        },
        "not_measured": ["latency as a benchmark metric", "GPU/VRAM utilisation", "cost"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def stage_c_aggregate() -> dict:
    answers = [json.loads(l) for l in ANSWERS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    scores = [json.loads(l) for l in SCORES_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]

    overall = {}
    for variant in ("base", "rag"):
        overall[variant] = {
            "correctness_pct": _pct_of_two([s[variant]["correctness"] for s in scores]),
            "relevance_pct": _pct_of_two([s[variant]["relevance"] for s in scores]),
            "hallucination_rate_pct": _rate_pct([s[variant]["hallucination"] for s in scores]),
            "groundedness_pct": _pct_of_two([s[variant]["groundedness"] for s in scores]),
            "n_scored": len(scores),
        }

    by_category: dict[str, dict] = {}
    categories = sorted({s["intended_category"] for s in scores})
    for category in categories:
        subset = [s for s in scores if s["intended_category"] == category]
        by_category[category] = {
            "n": len(subset),
            "base_correctness_pct": _pct_of_two([s["base"]["correctness"] for s in subset]),
            "rag_correctness_pct": _pct_of_two([s["rag"]["correctness"] for s in subset]),
            "base_hallucination_rate_pct": _rate_pct([s["base"]["hallucination"] for s in subset]),
            "rag_hallucination_rate_pct": _rate_pct([s["rag"]["hallucination"] for s in subset]),
            "rag_groundedness_pct": _pct_of_two([s["rag"]["groundedness"] for s in subset]),
        }

    def delta(key):
        b, r = overall["base"][key], overall["rag"][key]
        return (r - b) if (b is not None and r is not None) else None

    failure_distribution: dict[str, int] = {}
    for s in scores:
        key = s.get("failure_type", "not_available")
        failure_distribution[key] = failure_distribution.get(key, 0) + 1

    failure_by_category: dict[str, dict] = {}
    for category in categories:
        subset = [s for s in scores if s["intended_category"] == category]
        dist: dict[str, int] = {}
        for s in subset:
            key = s.get("failure_type", "not_available")
            dist[key] = dist.get(key, 0) + 1
        failure_by_category[category] = dist

    retrieval_ok_count = sum(1 for s in scores if (s.get("reference_retrieved") or {}).get("retrieved_ok"))

    payload = {
        "experiment": "E14-BaseVsRAG",
        "run_config": _run_config(answers),
        "overall": overall,
        "failure_type_distribution": failure_distribution,
        "failure_type_by_category": failure_by_category,
        "reference_retrieved_count": retrieval_ok_count,
        "reference_retrieved_pct": (retrieval_ok_count / len(scores) * 100) if scores else None,
        "deltas": {
            "correctness_pct": delta("correctness_pct"),
            "relevance_pct": delta("relevance_pct"),
            "hallucination_rate_pct": delta("hallucination_rate_pct"),
        },
        "by_category": by_category,
        "retrieval_precision_this_run": _this_run_retrieval_precision(answers),
        "retrieval_precision_preexisting_benchmarks": _preexisting_retrieval_precision(),
        "judge_parse_failures": sum(
            1 for s in scores for v in ("base", "rag") if "_parse_error" in (s[v].get("judge_raw") or {})
        ),
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "help"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    if stage == "queryset":
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        qs = build_queryset()
        with open(QUERYSET_PATH, "w", encoding="utf-8") as f:
            json.dump(qs, f, indent=2, ensure_ascii=False)
        print(f"queryset: {qs['n_queries']} queries {qs['composition']} -> {QUERYSET_PATH}")
    elif stage == "generate":
        stage_a_generate(limit=limit)
    elif stage == "score":
        stage_b_score(limit=limit)
    elif stage == "aggregate":
        payload = stage_c_aggregate()
        print(json.dumps({k: v for k, v in payload.items() if k != "run_config"}, indent=2, default=str))
    else:
        print("usage: python -m integration.eval.base_vs_rag {queryset|generate|score|aggregate} [limit]")
