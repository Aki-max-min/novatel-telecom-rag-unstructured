"""
Calibrate the two system thresholds on VALIDATION data only and record them in
data/eval/system_calibration.json (loaded by integration/qa/config.py).

    python -m integration.eval.calibrate_system --what retrieval
    python -m integration.eval.calibrate_system --what router --router laya_finetuned

retrieval  The layer-2 abstention gate: abstain from document-based answering when
           sigmoid(top CrossEncoder logit) < threshold.
           Data  : data/eval/abstention_val.jsonl (never abstention_test).
           Positives (should abstain): every expected="abstain" row.
           Negatives (should answer)  : document-answerable controls (synthetic + TRAI).
           Rule  : the threshold with the HIGHEST abstain recall such that the false-abstention rate on the
                   answerable document controls is <= MAX_FALSE_ABSTENTION (a stated policy choice, not a
                   learned value); ties -> lower threshold. The full curve is stored so the choice is auditable.
           Limit : this gate sees only retrieval relevance. Near-domain traps are on-topic by construction, so
                   this gate is expected to catch far fewer of them than the router or the generator rule does;
                   the measured per-category recall is stored.
router     The "low confidence -> treat as hybrid" threshold, via
           evaluate_router.calibrate_confidence_threshold on router_val only.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAL_PATH = ROOT / "data" / "eval" / "system_calibration.json"
MAX_FALSE_ABSTENTION = 0.10


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def load() -> dict:
    return json.loads(CAL_PATH.read_text(encoding="utf-8")) if CAL_PATH.exists() else {}


def save(section: str, payload: dict) -> None:
    cal = load()
    cal[section] = payload
    CAL_PATH.write_text(json.dumps(cal, indent=2, ensure_ascii=False), encoding="utf-8")


def calibrate_retrieval() -> dict:
    from integration.qa.config import QAConfig
    from integration.qa.retrieval import UnstructuredBackend

    rows = read_jsonl(ROOT / "data" / "eval" / "abstention_val.jsonl")
    backend = UnstructuredBackend()
    cfg = QAConfig()
    scored = []
    for r in rows:
        _, diag = backend.search(r["query"], cfg)
        scored.append({"id": r["id"], "expected": r["expected"], "category": r["category"],
                       "sigmoid": diag["top_crossencoder_sigmoid"]})

    answerable = [s for s in scored if s["category"].startswith("answerable_unstructured")]
    abstain = [s for s in scored if s["expected"] == "abstain"]
    candidates = sorted({0.0, *[s["sigmoid"] for s in scored]})
    curve = []
    for t in candidates:
        false_abstain = sum(s["sigmoid"] < t for s in answerable) / len(answerable)
        recall = sum(s["sigmoid"] < t for s in abstain) / len(abstain)
        curve.append({"threshold": round(t, 6), "false_abstention_rate": round(false_abstain, 4),
                      "abstain_recall": round(recall, 4)})
    feasible = [c for c in curve if c["false_abstention_rate"] <= MAX_FALSE_ABSTENTION]
    best = max(feasible, key=lambda c: (c["abstain_recall"], -c["threshold"]))

    by_cat = {}
    for s in abstain:
        by_cat.setdefault(s["category"], []).append(s["sigmoid"] < best["threshold"])
    payload = {
        "threshold": best["threshold"],
        "method": (f"highest abstain recall subject to false-abstention <= {MAX_FALSE_ABSTENTION} on "
                   "document-answerable controls; tie -> lower threshold"),
        "split": "abstention_val", "n_rows": len(rows), "n_answerable_docs": len(answerable), "n_abstain": len(abstain),
        "at_threshold": {k: best[k] for k in ("false_abstention_rate", "abstain_recall")},
        "abstain_recall_by_category_gate_only": {c: round(sum(v) / len(v), 3) for c, v in sorted(by_cat.items())},
        "sigmoid_median": {"answerable": round(sorted(s["sigmoid"] for s in answerable)[len(answerable) // 2], 4),
                           "abstain": round(sorted(s["sigmoid"] for s in abstain)[len(abstain) // 2], 4)},
        "curve": curve, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "retrieval": "combined 1,545-chunk FAISS + all-MiniLM-L6-v2 + ms-marco-MiniLM-L-6-v2 CrossEncoder",
    }
    save("retrieval", payload)
    return payload


def calibrate_router(name: str) -> dict:
    from integration.eval.evaluate_router import calibrate_confidence_threshold, read_split

    result = calibrate_confidence_threshold(name, read_split("val"))
    if "threshold" not in result:
        return result
    payload = {**result, "router": name, "split": "router_val",
               "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    save("router", payload)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", required=True, choices=["retrieval", "router"])
    ap.add_argument("--router", default="laya_finetuned")
    args = ap.parse_args()
    out = calibrate_retrieval() if args.what == "retrieval" else calibrate_router(args.router)
    print(json.dumps({k: v for k, v in out.items() if k != "curve"}, indent=2))
    print(f"saved -> {CAL_PATH}")


if __name__ == "__main__":
    main()
