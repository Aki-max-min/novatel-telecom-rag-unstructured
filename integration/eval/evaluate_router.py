"""
Router evaluation.

    python -m integration.eval.evaluate_router --split test --routers rule,embedding,laya_zeroshot,...
    python -m integration.eval.evaluate_router --split val  --routers ...   (for tuning decisions)

For every router that actually runs it reports, on the chosen split:
accuracy, per-class precision/recall/F1, the confusion matrix, hybrid recall,
out_of_scope recall, per-head accuracy (in_scope / needs_structured /
needs_unstructured), latency (median and p95) and model size. A router that
cannot load is recorded as "not evaluated (<reason>)" -- never skipped silently,
never substituted.

The TEST split must not be used to tune anything. The CLI refuses `--split test`
together with `--calibrate`; confidence thresholds are calibrated on VAL only
(see calibrate_confidence_threshold).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from query_router.base import LABELS, RouterUnavailable
from query_router.registry import build_router

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "data" / "eval"
OUT_DIR = ROOT / "data" / "experiments" / "router_eval"


def read_split(split: str) -> list:
    with open(EVAL_DIR / f"router_{split}.jsonl", "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "support": tp + fn}


def pctl(values: list, q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return round(s[k], 2)


def score(rows: list, preds: list) -> dict:
    """rows: gold records; preds: list of RouteDecision-dicts or None (failed)."""
    ok = [(r, p) for r, p in zip(rows, preds) if p is not None]
    failed = len(rows) - len(ok)
    gold = [r["label"] for r, _ in ok]
    pred = [p["label"] for _, p in ok]

    correct = sum(g == p for g, p in zip(gold, pred))
    per_class = {}
    for lab in LABELS:
        tp = sum(g == lab and p == lab for g, p in zip(gold, pred))
        fp = sum(g != lab and p == lab for g, p in zip(gold, pred))
        fn = sum(g == lab and p != lab for g, p in zip(gold, pred))
        per_class[lab] = prf(tp, fp, fn)
    confusion = {g: {p: 0 for p in LABELS} for g in LABELS}
    for g, p in zip(gold, pred):
        confusion[g][p] += 1

    head_acc = {}
    for head, key in (("in_scope", "in_scope"), ("needs_structured", "needs_structured"),
                      ("needs_unstructured", "needs_unstructured")):
        head_acc[head] = round(sum(bool(r[key]) == bool(p[key]) for r, p in ok) / len(ok), 4) if ok else None

    unamb = [(r, p) for r, p in ok if not r.get("ambiguous")]
    near = [(r, p) for r, p in ok if r["label"] == "out_of_scope" and "near-domain" in (r.get("notes") or "")]
    far = [(r, p) for r, p in ok if r["label"] == "out_of_scope" and "near-domain" not in (r.get("notes") or "")]

    lat = [p["latency_ms"] for _, p in ok]
    return {
        "n": len(rows), "n_scored": len(ok), "n_failed": failed,
        "accuracy": round(correct / len(ok), 4) if ok else None,
        "accuracy_excluding_ambiguous": round(sum(r["label"] == p["label"] for r, p in unamb) / len(unamb), 4) if unamb else None,
        "per_class": per_class,
        "macro_f1": round(sum(c["f1"] for c in per_class.values()) / len(per_class), 4),
        "hybrid_recall": per_class["hybrid"]["recall"],
        "out_of_scope_recall": per_class["out_of_scope"]["recall"],
        "out_of_scope_recall_far": round(sum(p["label"] == "out_of_scope" for _, p in far) / len(far), 4) if far else None,
        "out_of_scope_recall_near_domain": round(sum(p["label"] == "out_of_scope" for _, p in near) / len(near), 4) if near else None,
        "head_accuracy": head_acc,
        "confusion_matrix": confusion,
        "latency_ms": {"median": round(statistics.median(lat), 2) if lat else None, "p95": pctl(lat, 0.95)},
    }


def leakage_flagged_ids(rows: list) -> set:
    """Held-out ids flagged as near-duplicates of train/val by integration/eval/check_leakage.py (test split only)."""
    path = ROOT / "data" / "eval" / "router_leakage_report.json"
    if not path.exists() or not rows or rows[0].get("split") != "test":
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")).get("router_test_flagged_ids", []))


def run_router(name: str, rows: list, cfg: dict | None = None, warmup: bool = True) -> dict:
    try:
        router = build_router(name, cfg)
        ok, reason = router.available()
    except Exception as exc:  # noqa: BLE001
        return {"router": name, "status": f"not evaluated ({exc})"}
    if not ok:
        return {"router": name, "status": f"not evaluated ({reason})"}

    if warmup and rows:
        try:
            router.route(rows[0]["query"])  # exclude one-time model load from latency
        except Exception:  # noqa: BLE001
            pass

    preds, errors = [], []
    for r in rows:
        try:
            preds.append(router.route(r["query"]).as_dict())
        except Exception as exc:  # noqa: BLE001
            preds.append(None)
            errors.append({"id": r["id"], "error": str(exc)[:160]})
    result = {"router": name, "status": "evaluated", "model_id": router.model_id,
              "size_params": router.size_params, "metrics": score(rows, preds), "errors": errors[:10]}
    flagged = leakage_flagged_ids(rows)
    if flagged:
        kept = [(r, p) for r, p in zip(rows, preds) if r["id"] not in flagged]
        result["metrics"]["accuracy_excluding_leakage_flagged"] = {
            "n_excluded": len(rows) - len(kept),
            "accuracy": score([r for r, _ in kept], [p for _, p in kept])["accuracy"]}
    result["predictions"] = [
        {"id": r["id"], "query": r["query"], "gold": r["label"],
         "pred": (p["label"] if p else None), "confidence": (p["confidence"] if p else None),
         "reasoning": (p.get("reasoning") if p else None)}
        for r, p in zip(rows, preds)
    ]
    return result


def calibrate_confidence_threshold(name: str, val_rows: list, cfg: dict | None = None) -> dict:
    """
    Choose the router-confidence threshold ON VALIDATION DATA ONLY.

    Rule being calibrated (system behaviour): a decision whose confidence is
    below the threshold is treated as `hybrid` (retrieve from both sources --
    safer than a wrong single route). The threshold maximises 4-class accuracy
    of the resulting "route-with-low-confidence-to-hybrid" policy on VAL; ties go
    to the LOWER threshold (fewer forced hybrids).
    """
    router = build_router(name, cfg)
    ok, reason = router.available()
    if not ok:
        return {"router": name, "status": f"not calibrated ({reason})"}
    decisions = [router.route(r["query"]) for r in val_rows]
    grid = [round(0.5 + 0.02 * i, 2) for i in range(0, 25)]
    best_t, best_acc, curve = 0.5, -1.0, []
    for t in grid:
        correct = 0
        for r, d in zip(val_rows, decisions):
            label = d.label if d.confidence >= t else "hybrid"
            correct += label == r["label"]
        acc = correct / len(val_rows)
        curve.append({"threshold": t, "val_accuracy": round(acc, 4)})
        if acc > best_acc + 1e-12:
            best_t, best_acc = t, acc
    return {"router": name, "status": "calibrated_on_val", "n_val": len(val_rows), "threshold": best_t,
            "val_accuracy_at_threshold": round(best_acc, 4),
            "val_accuracy_no_threshold": curve[0]["val_accuracy"], "curve": curve}


def markdown_table(results: list) -> str:
    lines = ["| router | model id | params | acc | macro-F1 | hybrid R | OOS R | OOS R (near) | median ms | p95 ms |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if r["status"] != "evaluated":
            lines.append(f"| {r['router']} | - | - | {r['status']} | | | | | | |")
            continue
        m = r["metrics"]
        size = f"{r['size_params'] / 1e6:.0f}M" if r.get("size_params") else "n/a"
        lines.append(
            f"| {r['router']} | {r['model_id']} | {size} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} | "
            f"{m['hybrid_recall']:.3f} | {m['out_of_scope_recall']:.3f} | "
            f"{m['out_of_scope_recall_near_domain'] if m['out_of_scope_recall_near_domain'] is not None else 'n/a'} | "
            f"{m['latency_ms']['median']} | {m['latency_ms']['p95']} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["train", "val", "test"])
    ap.add_argument("--routers", required=True, help="comma-separated registry names")
    ap.add_argument("--tag", default="")
    ap.add_argument("--calibrate", action="store_true", help="calibrate confidence threshold (VAL only)")
    args = ap.parse_args()

    if args.calibrate and args.split != "val":
        raise SystemExit("--calibrate is only allowed with --split val (never tune on test)")

    rows = read_split(args.split)
    names = [n.strip() for n in args.routers.split(",") if n.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    results = []
    for name in names:
        print(f"--> {name} on {args.split} ({len(rows)} queries)", flush=True)
        t0 = time.time()
        res = run_router(name, rows)
        if args.calibrate and res["status"] == "evaluated":
            res["confidence_calibration"] = calibrate_confidence_threshold(name, rows)
        results.append(res)
        if res["status"] == "evaluated":
            m = res["metrics"]
            print(f"    acc={m['accuracy']} macroF1={m['macro_f1']} hybridR={m['hybrid_recall']} "
                  f"oosR={m['out_of_scope_recall']} failed={m['n_failed']} ({time.time()-t0:.0f}s)", flush=True)
        else:
            print(f"    {res['status']}", flush=True)

    payload = {"split": args.split, "n": len(rows), "timestamp_utc": stamp, "results": results}
    path = OUT_DIR / f"router_eval_{args.split}_{stamp}{('_' + args.tag) if args.tag else ''}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    print("\n" + markdown_table(results))
    print(f"\nsaved: {path}")


if __name__ == "__main__":
    main()
