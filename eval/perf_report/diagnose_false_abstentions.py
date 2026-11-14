"""
Diagnosis (read-only, no LLM) of the in-scope questions the system refused in the saved abstention TEST run.

    python eval/perf_report/diagnose_false_abstentions.py

Reads data/experiments/system_eval/abstention_test_20261031T142243Z_final_test.json (saved, run once) and data/eval/abstention_test.jsonl (ground truth).
For each false abstention: which layer refused (1 router, 2 retrieval-confidence gate, 3 generator rule), what the router decided, and -- by re-running ONLY the
document retrieval (MiniLM + FAISS + CrossEncoder, no generation) -- whether a gold document is retrieved and how the gate's score compares with the calibrated
threshold. Nothing is changed: no threshold, router, prompt or index is touched. Causes are inferences from these numbers and are labelled as such.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "structured")]

from integration.qa.config import QAConfig  # noqa: E402
from integration.qa.retrieval import UnstructuredBackend  # noqa: E402

SAVED = ROOT / "data" / "experiments" / "system_eval" / "abstention_test_20261031T142243Z_final_test.json"
GROUND_TRUTH = ROOT / "data" / "eval" / "abstention_test.jsonl"
OUT = ROOT / "results" / "perf_report" / "false_abstentions.json"
LAYER = {1: "router", 2: "retrieval gate", 3: "generator"}


def main() -> None:
    saved = json.loads(SAVED.read_text(encoding="utf-8"))
    records = {r["id"]: r for r in saved["records"]}
    gt = {r["id"]: r for r in (json.loads(l) for l in GROUND_TRUTH.read_text(encoding="utf-8").splitlines() if l.strip())}
    cfg = QAConfig()
    backend = UnstructuredBackend()
    rows = []
    for fa in saved["summary"]["false_abstentions"]:
        rec, truth = records[fa["id"]], gt[fa["id"]]
        gold_docs = (truth.get("ground_truth") or {}).get("expected_document_ids", [])
        evidence, diag = backend.search(truth["query"], cfg)
        docs = []
        for e in evidence:
            d = e["metadata"]["document_id"]
            if d not in docs:
                docs.append(d)
        gold_rank = next((i for i, d in enumerate(docs, 1) if d in gold_docs), None)
        sig = diag["top_crossencoder_sigmoid"]
        layer = LAYER[rec["layer"]]
        thr = cfg.retrieval_conf_threshold
        if rec["layer"] == 2:
            cause = (f"retrieval gate: the top CrossEncoder score (sigmoid {sig:.4f}) is below the calibrated threshold {thr:.4f}; "
                     + (f"the gold document {gold_docs[0] if gold_docs else ''} IS retrieved (rank {gold_rank}), so the gate refused answerable evidence: the ms-marco CrossEncoder gives "
                        "low scores to this broad / regulatory-style question (inferred)" if gold_rank else
                        "and no gold document is in the top 5, so this is a retrieval miss that the gate correctly turned into a refusal (inferred)"))
        elif rec["layer"] == 3:
            cause = (f"generator rule: the retrieval gate passed (sigmoid {sig:.4f} >= {thr:.4f}) but the generator answered INSUFFICIENT_EVIDENCE; "
                     + (f"a gold document is in the top 5 at rank {gold_rank}, so the evidence was present and the strict 'answer only from evidence' rule judged it insufficient (inferred)"
                        if gold_rank else "no gold document is in the top 5, so the generator had no matching evidence (retrieval miss, inferred)"))
        else:
            cause = "router: the router judged an in-scope question out of scope"
        rows.append({"id": fa["id"], "question": truth["query"], "category": truth["category"], "expected": truth["expected"],
                     "gold_documents": gold_docs, "layer_that_abstained": layer, "layer_number": rec["layer"], "saved_reason": rec["reason"],
                     "router": {"name": rec["router"], "label": rec["router_label"], "confidence": rec["router_confidence"], "final_route": rec["final_route"]},
                     "retrieval_top5_documents": docs, "gold_rank_in_top5": gold_rank, "top_crossencoder_sigmoid": sig,
                     "calibrated_threshold": thr, "likely_cause": cause})
        print(f"{fa['id']} [{layer}] gold_rank={gold_rank} sigmoid={sig:.4f} | {truth['query'][:70]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": str(SAVED.relative_to(ROOT)).replace("\\", "/"), "note": "diagnosis only; nothing was changed", "rows": rows}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print("saved", OUT)


if __name__ == "__main__":
    main()
