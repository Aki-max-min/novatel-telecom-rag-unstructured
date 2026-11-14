"""
End-to-end abstention evaluation of integration.qa.system.answer_query.

    python -m integration.eval.evaluate_abstention --split val  --router auto --tag dev
    python -m integration.eval.evaluate_abstention --split test --router auto --tag final     # read ONCE

Rows (data/eval/abstention_{val,test}.jsonl):
    expected="abstain"  out-of-scope + near-domain traps + non-existent entities
    expected="answer"   answerable controls drawn from existing benchmarks

Reported
    abstention precision = abstained&should / all abstained
    abstention recall    = abstained&should / should abstain      (overall and per category)
    false-abstention rate = abstained / answerable controls
    which layer stopped each abstention (1 router, 2 retrieval gate, 3 generator)
    wrong answers on abstain-expected rows are listed verbatim (these are hallucination risks)
    any abstention that still carried a citation (must be 0)

The retrieval threshold and router threshold come from data/eval/system_calibration.json (validation-calibrated).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from integration.qa.config import QAConfig
from integration.qa.system import answer_query

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "experiments" / "system_eval"


def read_rows(split: str) -> list[dict]:
    return [json.loads(l) for l in open(ROOT / "data" / "eval" / f"abstention_{split}.jsonl", encoding="utf-8") if l.strip()]


def summarise(records: list[dict]) -> dict:
    should = [r for r in records if r["expected"] == "abstain"]
    answerable = [r for r in records if r["expected"] == "answer"]
    abstained = [r for r in records if r["abstained"]]
    tp = [r for r in should if r["abstained"]]
    by_cat = {}
    for r in should:
        by_cat.setdefault(r["category"], []).append(r["abstained"])
    layers = {}
    for r in abstained:
        layers[str(r["layer"])] = layers.get(str(r["layer"]), 0) + 1
    return {
        "n": len(records), "n_should_abstain": len(should), "n_answerable": len(answerable), "n_abstained": len(abstained),
        "abstention_precision": round(len(tp) / len(abstained), 4) if abstained else None,
        "abstention_recall": round(len(tp) / len(should), 4) if should else None,
        "false_abstention_rate": round(sum(r["abstained"] for r in answerable) / len(answerable), 4) if answerable else None,
        "recall_by_category": {c: {"n": len(v), "recall": round(sum(v) / len(v), 3)} for c, v in sorted(by_cat.items())},
        "abstentions_by_layer": layers,
        "abstentions_with_citations": sum(1 for r in abstained if r["n_citations"] > 0),
        "wrong_answers_on_should_abstain": [
            {"id": r["id"], "query": r["query"], "category": r["category"], "route": r["final_route"], "answer": r["answer_text"][:300]}
            for r in should if not r["abstained"]],
        "false_abstentions": [
            {"id": r["id"], "query": r["query"], "route": r["final_route"], "layer": r["layer"], "reason": r["reason"]}
            for r in answerable if r["abstained"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True, choices=["val", "test"])
    ap.add_argument("--router", default="auto")
    ap.add_argument("--tag", default="")
    ap.add_argument("--verifier", default="lexical", choices=["lexical", "nli"],
                    help="abstention does not depend on the verifier; lexical keeps the run fast")
    args = ap.parse_args()

    rows = read_rows(args.split)
    cfg = QAConfig(router=args.router, verifier=args.verifier)
    records = []
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        res = answer_query(row["query"], cfg)
        records.append({
            "id": row["id"], "query": row["query"], "expected": row["expected"], "category": row["category"],
            "abstained": res["abstained"], "layer": res["abstention"]["layer"], "reason": res["abstention"]["reason"],
            "final_route": res["route"].get("final_route"), "router": res["router_name"],
            "router_label": res["route"].get("label"), "router_confidence": res["route"].get("confidence"),
            "n_citations": sum(len(s["citations"]) for s in res["sentences"]), "answer_text": res["answer_text"],
            "error": res.get("error"), "total_ms": res["timings"].get("total_ms"),
        })
        print(f"[{i}/{len(rows)}] {row['expected']:7s} abstained={res['abstained']!s:5s} route={records[-1]['final_route']} "
              f"{row['query'][:60]}", flush=True)

    summary = summarise(records)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"abstention_{args.split}_{stamp}{('_' + args.tag) if args.tag else ''}.json"
    payload = {"experiment": "abstention", "split": args.split, "timestamp_utc": stamp, "config": cfg.as_dict(),
               "runtime_s": round(time.time() - t0, 1), "summary": summary, "records": records}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("wrong_answers_on_should_abstain", "false_abstentions")}, indent=2))
    print(f"wrong answers on should-abstain: {len(summary['wrong_answers_on_should_abstain'])}; "
          f"false abstentions: {len(summary['false_abstentions'])}\nsaved: {path}")


if __name__ == "__main__":
    main()
