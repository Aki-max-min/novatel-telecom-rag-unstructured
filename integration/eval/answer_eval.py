"""
Answer-quality evaluation for the E14 integrated RAG pipeline.

Four DeepEval metrics, judged by the SAME local Ollama model the pipeline
generates answers with (no external API, no ground-truth-answer
fabrication):
  - AnswerRelevancyMetric      -> answer relevancy
  - ContextualRelevancyMetric  -> contextual relevancy
  - FaithfulnessMetric         -> faithfulness / hallucination (LLM-judged)
  - ContextualPrecisionMetric  -> retrieval precision (LLM-judged)

Plus a SECOND, deterministic faithfulness signal from faithfulness_nli.py
(local NLI model, CPU-only, no LLM) -- added alongside the judge score, not
replacing it, specifically because the judge is a weak 3B/7B model and the
deterministic structured-fact checker (factcheck.py) only ever covers
structured-type queries, leaving unstructured/hybrid answers with no
deterministic groundedness signal at all until now.

ContextualPrecisionMetric is the one DeepEval metric that structurally
requires an `expected_output`. We do NOT invent a ground-truth answer for
it. Instead we build a mechanically-derived "expected_output_proxy" out of
ground truth that already exists in the repo (expected_document_ids for
unstructured queries, expected_table/filter for structured queries) -- see
_expected_output_proxy(). This is disclosed, not hidden: every eval record
carries the literal proxy string used, and the printed report repeats the
caveat from requirement 14.

Alongside the LLM-judged ContextualPrecisionMetric, deterministic_metrics()
computes real R@1/R@3/R@5/MRR@10 from the same expected_document_ids, with
no LLM involved, so judge-vs-deterministic can be compared directly.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
)
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase

from integration.eval.factcheck import check_structured_claims
from integration.eval.faithfulness_nli import (
    DEFAULT_THRESHOLD as NLI_DEFAULT_THRESHOLD,
    NLI_MODEL_NAME,
    score_answer_faithfulness,
)
from integration.rag.context_builder import DEFAULT_TOP_N, build_context
from integration.rag.fuse import RRF_K, reciprocal_rank_fusion
from integration.rag.llm_client import OllamaClient
from integration.rag.pipeline import EMBEDDING_MODEL_NAME, RagPipeline

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SYNTHETIC_EVAL_PATH = PROJECT_ROOT / "data" / "vectorstore" / "retrieval_evaluation.json"
PUBLIC_EVAL_PATH = PROJECT_ROOT / "data" / "experiments" / "public_pdfs" / "public_pdf_queries.json"
STRUCTURED_BENCHMARK_PATH = PROJECT_ROOT / "structured" / "benchmark.json"

RESULTS_DIR = PROJECT_ROOT / "data" / "experiments" / "integrated_rag"

FAITHFULNESS_JUDGE_CAVEAT = (
    "CAVEAT: AnswerRelevancy, ContextualRelevancy, Faithfulness(judge) and "
    "ContextualPrecision above are judged by a local 7B/3B Ollama model "
    "(qwen2.5), not a ground-truth human or a large frontier model. These "
    "scores must be human spot-checked before being treated as reliable -- "
    "they are a signal, not ground truth. Compare them against the "
    "deterministic R@k/MRR@10 numbers AND the deterministic NLI faithfulness "
    "score (no LLM involved in either) printed alongside."
)

NA = "not available"


class OllamaDeepEvalModel(DeepEvalBaseLLM):
    """Lets DeepEval's metrics use our local Ollama model as judge,
    instead of calling out to an external API."""

    def __init__(self, client: OllamaClient | None = None):
        self.client = client or OllamaClient()
        super().__init__()

    def load_model(self):
        return self.client

    def generate(self, prompt: str) -> str:
        return self.client.chat(system="You are an evaluation judge. Follow the instructions exactly.", user=prompt)

    async def a_generate(self, prompt: str) -> str:
        return self.generate(prompt)

    def get_model_name(self) -> str:
        return f"ollama:{self.client.model}"


def _load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_eval_set(limit: int | None = None) -> list[dict]:
    """Combines the EXISTING retrieval eval queries (synthetic + public +
    structured benchmark) into one uniform list. No new queries or
    ground-truth answers are invented."""
    items = []

    synthetic = _load_json(SYNTHETIC_EVAL_PATH)
    for row in synthetic.get("results", synthetic if isinstance(synthetic, list) else []):
        items.append({
            "query_id": row["question_id"],
            "question": row["question"],
            "query_type": "unstructured",
            "expected_document_ids": row["expected_document_ids"],
        })

    public = _load_json(PUBLIC_EVAL_PATH)
    for row in public:
        items.append({
            "query_id": row["query_id"],
            "question": row["query"],
            "query_type": "unstructured",
            "expected_document_ids": row["relevant_documents"],
        })

    structured = _load_json(STRUCTURED_BENCHMARK_PATH)
    for row in structured:
        items.append({
            "query_id": row["id"],
            "question": row["question"],
            "query_type": "structured",
            "expected_table": row["expected_table"],
            "expected_filter_column": row.get("expected_filter_column"),
            "expected_filter_value": row.get("expected_filter_value"),
        })

    if limit is not None:
        # Keep a mix of query types in the subset rather than truncating
        # straight through (which would be all-unstructured).
        per_type: dict[str, list[dict]] = {}
        for item in items:
            per_type.setdefault(item["query_type"], []).append(item)
        subset = []
        types = list(per_type.keys())
        i = 0
        while len(subset) < limit and any(per_type[t] for t in types):
            t = types[i % len(types)]
            if per_type[t]:
                subset.append(per_type[t].pop(0))
            i += 1
        items = subset[:limit]

    return items


def _classify_query_type(item: dict, structured_results: list[dict], unstructured_results: list[dict]) -> str:
    if item["query_type"] == "structured":
        return "structured"
    if structured_results and unstructured_results:
        return "hybrid"
    return "unstructured"


def _expected_output_proxy(item: dict) -> str:
    """Mechanically derived from EXISTING ground truth -- not an invented
    answer. See module docstring."""
    if item["query_type"] == "unstructured":
        docs = ", ".join(item["expected_document_ids"])
        return f"A correct answer must be grounded in evidence from document(s): {docs}."
    table = item["expected_table"]
    column = item.get("expected_filter_column")
    value = item.get("expected_filter_value")
    if column:
        return f"A correct answer must be grounded in the '{table}' table, filtered on {column}={value}."
    return f"A correct answer must be grounded in the '{table}' table."


def _reciprocal_rank(retrieved: list[str], expected: set[str]) -> float:
    for rank, doc_id in enumerate(retrieved, start=1):
        if doc_id in expected:
            return 1.0 / rank
    return 0.0


def deterministic_metrics(records: list[dict]) -> dict:
    """R@1/R@3/R@5/MRR@10 computed with no LLM, from expected_document_ids,
    over unstructured-type eval records only. Also reports a simple
    structured hit-rate (correct table retrieved) for structured-type
    records, kept separate since it isn't a ranked-document metric."""
    unstructured = [r for r in records if r["item"]["query_type"] == "unstructured"]
    structured = [r for r in records if r["item"]["query_type"] == "structured"]

    k_values = (1, 3, 5, 10)
    hits = {k: 0 for k in k_values}
    mrr_total = 0.0

    for record in unstructured:
        expected = set(record["item"]["expected_document_ids"])
        retrieved = [
            e["metadata"].get("provenance", {}).get("document_id") or e["record_id"]
            for e in record["evidence"]
            if e["source"] == "unstructured"
        ]
        for k in k_values:
            if any(doc_id in expected for doc_id in retrieved[:k]):
                hits[k] += 1
        mrr_total += _reciprocal_rank(retrieved, expected)

    total_unstructured = len(unstructured) or 1
    result = {
        f"R@{k}": hits[k] / total_unstructured for k in k_values
    }
    result["MRR@10"] = mrr_total / total_unstructured
    result["n_unstructured_queries"] = len(unstructured)

    structured_hits = 0
    for record in structured:
        expected_table = record["item"]["expected_table"]
        if any(e["dataset"] == expected_table for e in record["evidence"] if e["source"] == "structured"):
            structured_hits += 1
    result["structured_table_hit_rate"] = structured_hits / (len(structured) or 1)
    result["n_structured_queries"] = len(structured)

    return result


def run_deepeval_metrics(records: list[dict], judge_model: OllamaDeepEvalModel) -> dict:
    metrics = [
        AnswerRelevancyMetric(model=judge_model, include_reason=True),
        ContextualRelevancyMetric(model=judge_model, include_reason=True),
        FaithfulnessMetric(model=judge_model, include_reason=True),
        ContextualPrecisionMetric(model=judge_model, include_reason=True),
    ]

    per_query = []
    for record in records:
        test_case = LLMTestCase(
            input=record["item"]["question"],
            actual_output=record["answer"],
            retrieval_context=[e["content"] for e in record["evidence"]] or ["(no evidence retrieved)"],
            expected_output=_expected_output_proxy(record["item"]),
        )
        scores = {}
        for metric in metrics:
            try:
                metric.measure(test_case)
                scores[metric.__class__.__name__] = {
                    "score": metric.score,
                    "reason": getattr(metric, "reason", None),
                }
            except Exception as exc:  # judge/model failure for this one metric -- don't abort the run
                scores[metric.__class__.__name__] = {"score": None, "error": str(exc)}
        per_query.append({"query_id": record["item"]["query_id"], "scores": scores})

    aggregate = {}
    for metric_name in ["AnswerRelevancyMetric", "ContextualRelevancyMetric", "FaithfulnessMetric", "ContextualPrecisionMetric"]:
        values = [q["scores"][metric_name]["score"] for q in per_query if q["scores"][metric_name]["score"] is not None]
        aggregate[metric_name] = sum(values) / len(values) if values else None

    return {"per_query": per_query, "aggregate": aggregate}


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def run_nli_metrics(records: list[dict], threshold: float = NLI_DEFAULT_THRESHOLD) -> dict:
    """Deterministic NLI faithfulness, computed for every record regardless
    of query_type (unlike factcheck.py, which only ever covers
    structured-cited sentences)."""
    per_query = {}
    for record in records:
        result = score_answer_faithfulness(record["answer"], record["evidence"], threshold=threshold)
        per_query[record["item"]["query_id"]] = result

    by_type: dict[str, list[float]] = {}
    for record in records:
        qid = record["item"]["query_id"]
        qtype = record["query_type"]
        by_type.setdefault(qtype, []).append(per_query[qid]["nli_faithfulness"])

    aggregate = {"overall": _mean([r["nli_faithfulness"] for r in per_query.values()])}
    for qtype, values in by_type.items():
        aggregate[qtype] = _mean(values)

    return {"per_query": per_query, "aggregate": aggregate, "threshold": threshold, "model": NLI_MODEL_NAME}


def _detect_hardware() -> dict:
    """Best-effort hardware detection. Never invents a value -- any failure
    (no nvidia-smi, non-Windows ctypes call, etc.) falls back to "not
    available" for that field only."""
    gpu_info = NA
    try:
        import subprocess

        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            gpu_info = proc.stdout.strip().splitlines()[0]
    except Exception:
        pass

    ram_info = NA
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        ram_info = f"{stat.ullTotalPhys / (1024 ** 3):.1f} GiB"
    except Exception:
        pass

    return {"gpu": gpu_info, "ram": ram_info}


def _detect_quantization(model_name: str) -> str:
    """Real value via ollama.show() (details.quantization_level) -- NOT
    invented. Falls back to "not available" if ollama isn't reachable or
    the field is absent."""
    try:
        import ollama

        info = ollama.show(model_name)
        details = getattr(info, "details", None)
        quant = getattr(details, "quantization_level", None) if details else None
        if quant:
            return quant
    except Exception:
        pass
    return NA


def build_run_config(pipeline: RagPipeline, judge_model: OllamaDeepEvalModel, eval_items: list[dict]) -> dict:
    """Persists what we can actually obtain. Missing -> "not available",
    never invented. See requirement B of the NLI task."""
    hardware = _detect_hardware()
    query_type_counts: dict[str, int] = {}
    for item in eval_items:
        query_type_counts[item["query_type"]] = query_type_counts.get(item["query_type"], 0) + 1

    return {
        "generation_model": pipeline.llm_client.model,
        "quantization": _detect_quantization(pipeline.llm_client.model),
        "judge_model": judge_model.get_model_name(),
        "nli_model": NLI_MODEL_NAME,
        "nli_threshold": NLI_DEFAULT_THRESHOLD,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "fusion_method": "RRF",
        "rrf_k": RRF_K,
        "top_n_context": DEFAULT_TOP_N,
        "eval_set_size": len(eval_items),
        "eval_set_composition": query_type_counts,
        "detected_gpu": hardware["gpu"],
        "detected_ram": hardware["ram"],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }


def _get_evidence_only(pipeline: RagPipeline, question: str, top_n_context: int = DEFAULT_TOP_N) -> list[dict]:
    """Retrieval + fusion + context ONLY -- no generation, no LLM call.
    Used to re-derive evidence for a cached answer without re-running
    generation (requirement: never regenerate an answer that's cached)."""
    structured_results = pipeline.structured.search(question)
    unstructured_results = pipeline.unstructured.search(question)
    fused = reciprocal_rank_fusion(structured_results, unstructured_results)
    context = build_context(fused, top_n=top_n_context)
    return context["evidence"]


def save_results(payload: dict, label: str = "E14") -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{timestamp}_{label}.json"
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing run: {out_path}")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    return out_path


def run_eval(limit: int | None = None, label: str = "E14", nli_threshold: float = NLI_DEFAULT_THRESHOLD) -> dict:
    """
    Builds the eval set (optionally truncated to `limit`), runs every query
    through one shared RagPipeline (full generation -- this is for queries
    with no cached answer), computes deterministic + DeepEval + NLI metrics
    + deterministic factcheck, persists run_config, saves machine-readable
    JSON, and returns the full payload (also printed by callers).
    """
    eval_items = build_eval_set(limit=limit)
    pipeline = RagPipeline()
    judge_model = OllamaDeepEvalModel(client=pipeline.llm_client)
    run_config = build_run_config(pipeline, judge_model, eval_items)

    records = []
    try:
        for item in eval_items:
            result = pipeline.run_query(item["question"])
            query_type = _classify_query_type(item, result["structured_results"], result["unstructured_results"])
            factcheck = check_structured_claims(result["answer"], result["evidence"])
            records.append({
                "item": item,
                "query_type": query_type,
                "answer": result["answer"],
                "evidence": result["evidence"],
                "factcheck": factcheck,
            })
    finally:
        pipeline.close()

    det_metrics = deterministic_metrics(records)
    deepeval_results = run_deepeval_metrics(records, judge_model)
    nli_results = run_nli_metrics(records, threshold=nli_threshold)

    judge_faithfulness_by_id = {
        q["query_id"]: q["scores"]["FaithfulnessMetric"]["score"]
        for q in deepeval_results["per_query"]
    }

    factcheck_totals = {
        "total_checked_claims": sum(r["factcheck"]["checked_claims"] for r in records),
        "total_unsupported_claims": sum(r["factcheck"]["unsupported_claims"] for r in records),
    }

    by_query_type: dict[str, int] = {}
    for record in records:
        by_query_type[record["query_type"]] = by_query_type.get(record["query_type"], 0) + 1

    payload = {
        "experiment": label,
        "description": "Integrated RAG: structured SQL + unstructured FAISS/metadata retrieval, "
                        "RRF fusion, local Ollama generation. No KG/ontology/document-graph/ColPali wired in.",
        "n_queries": len(records),
        "query_type_counts": by_query_type,
        "run_config": run_config,
        "deterministic_metrics": det_metrics,
        "deepeval_metrics": deepeval_results,
        "nli_metrics": nli_results,
        "factcheck": factcheck_totals,
        "faithfulness_judge_caveat": FAITHFULNESS_JUDGE_CAVEAT,
        "per_query_records": [
            {
                "query_id": r["item"]["query_id"],
                "question": r["item"]["question"],
                "query_type": r["query_type"],
                "answer": r["answer"],
                "evidence": r["evidence"],
                "factcheck": r["factcheck"],
                "comparison": {
                    "judge_faithfulness": judge_faithfulness_by_id.get(r["item"]["query_id"]),
                    "nli_faithfulness": nli_results["per_query"][r["item"]["query_id"]]["nli_faithfulness"],
                    "factcheck_mismatch_count": r["factcheck"]["unsupported_claims"],
                },
            }
            for r in records
        ],
    }

    out_path = save_results(payload, label=label)
    payload["_saved_to"] = str(out_path)
    return payload


def rescore_existing_run(path: Path, nli_threshold: float = NLI_DEFAULT_THRESHOLD) -> list[dict]:
    """
    Loads a prior result JSON and, for every cached per-query answer,
    re-derives the evidence via retrieval ONLY (no LLM call -- neither
    generation nor judging) and computes the NLI faithfulness score. Joins
    with the judge_faithfulness and factcheck_mismatch_count already present
    in that file for a three-way comparison. Does NOT regenerate answers,
    does NOT re-run the DeepEval judge.
    """
    old = _load_json(path)

    judge_scores_by_id = {
        q["query_id"]: q["scores"]["FaithfulnessMetric"]["score"]
        for q in old["deepeval_metrics"]["per_query"]
    }

    pipeline = RagPipeline()
    rows = []
    try:
        for record in old["per_query_records"]:
            evidence = _get_evidence_only(pipeline, record["question"])
            nli_result = score_answer_faithfulness(record["answer"], evidence, threshold=nli_threshold)
            rows.append({
                "query_id": record["query_id"],
                "query_type": record["query_type"],
                "question": record["question"],
                "answer": record["answer"],
                "judge_faithfulness": judge_scores_by_id.get(record["query_id"]),
                "nli_faithfulness": nli_result["nli_faithfulness"],
                "nli_detail": nli_result,
                "factcheck_mismatch_count": record["factcheck"]["unsupported_claims"],
            })
    finally:
        pipeline.close()
    return rows


def print_comparison_table(rows: list[dict]) -> None:
    print(f"{'query_id':10} {'query_type':12} {'judge_faith':12} {'nli_faith':10} {'factcheck_mismatch':18}")
    for row in rows:
        jf = f"{row['judge_faithfulness']:.3f}" if row["judge_faithfulness"] is not None else NA
        nf = f"{row['nli_faithfulness']:.3f}" if row["nli_faithfulness"] is not None else NA
        print(f"{row['query_id']:10} {row['query_type']:12} {jf:12} {nf:10} {row['factcheck_mismatch_count']:18}")


def print_report(payload: dict) -> None:
    print(f"\n=== {payload['experiment']} eval report ({payload['n_queries']} queries) ===")
    print(f"Query types: {payload['query_type_counts']}")

    print("\n-- run_config --")
    for key, value in payload["run_config"].items():
        print(f"  {key}: {value}")

    print("\n-- Deterministic retrieval metrics (no LLM) --")
    for key, value in payload["deterministic_metrics"].items():
        print(f"  {key}: {value}")

    print("\n-- DeepEval metrics (LLM-judged) --")
    for metric_name, score in payload["deepeval_metrics"]["aggregate"].items():
        print(f"  {metric_name}: {score}")

    print("\n-- NLI faithfulness (deterministic, CPU, no LLM) --")
    for key, value in payload["nli_metrics"]["aggregate"].items():
        print(f"  {key}: {value}")

    print("\n-- Deterministic factcheck --")
    print(f"  checked claims: {payload['factcheck']['total_checked_claims']}")
    print(f"  unsupported claims: {payload['factcheck']['total_unsupported_claims']}")

    print(f"\n{payload['faithfulness_judge_caveat']}")
    print(f"\nSaved to: {payload.get('_saved_to')}")


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    report = run_eval(limit=n, label="E14-subset" if n < 74 else "E14-full")
    print_report(report)
