"""
Metrics that need NO LLM, computed from results/perf_report/raw_answers.jsonl only (retrieval, database-row coverage, latency, prompt size, routing,
answer-level determinism). Written because the judge stage could not run (Ollama was unavailable); labelled PARTIAL in the output.

    python eval/perf_report/partial_metrics.py   ->   results/perf_report/partial_metrics_no_llm.json
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402
import run_report as rr  # noqa: E402

LATENCY_OUTLIER_S = 120   # records slower than this coincide with machine suspend (log timestamp jumps); excluded from latency statistics


def main() -> None:
    qs, raw, _ = rr.load()
    arms = h.ARMS + [h.REPRO_ARM]
    out = {"status": "PARTIAL: LLM-free metrics only; correctness / relevance / groundedness / hallucination / citation metrics are NOT computed",
           "n_records": len(raw), "records_per_arm": dict(Counter(k[0] for k in raw)),
           "latency_outlier_rule": f"records are excluded from latency statistics when more than {h.SUSPECT_GAP_S} s passed since the previous record completed, or the record itself took more than {h.SLOW_RECORD_S} s (machine suspend / restart)",
           "arms": {}}
    core = {q for q in qs if qs[q]["is_core"]}
    flagged = h.flag_latency_records(list(raw.values()))
    for arm in arms:
        runs = rr.runs_of(raw, arm)
        if not runs:
            continue
        recs = [raw[k] for k in raw if k[0] == arm]
        lat_all = [r["latency_s"] for r in recs]
        lat = [raw[k]["latency_s"] for k in raw if k[0] == arm and k not in flagged]
        a = {"runs": runs, "n": len(recs), "latency_median_s": round(statistics.median(lat), 2), "latency_p95_s": h.p95(lat),
             "latency_outliers_excluded": len(lat_all) - len(lat),
             "prompt_tokens_median": statistics.median([r["prompt_tokens"] for r in recs if r["prompt_tokens"]]) if any(r["prompt_tokens"] for r in recs) else None,
             "prompt_tokens_max": max(r["prompt_tokens"] for r in recs), "n_cached": sum(1 for r in recs if r.get("cached")),
             "n_abstained_by_router_or_empty_context": sum(1 for r in recs if r.get("abstained"))}
        if arm != "A":
            a["retrieval_docq"] = rr.retrieval_metrics(arm, qs, raw, runs)
            a["retrieval_core14"] = rr.retrieval_metrics(arm, qs, raw, runs, core)
            a["retrieval_identical_across_runs"] = not rr.retrieval_is_deterministic(arm, qs, raw, runs)
            a["db_rowcov_pct_per_run"] = rr.db_rowcov(arm, qs, raw, runs)
        if arm in ("router", "C"):
            a["routes"] = dict(Counter((r["route"] or {}).get("final") for r in recs))
            a["router_names"] = dict(Counter((r["route"] or {}).get("router") for r in recs))
        if arm in ("ontology", "docgraph", "C"):
            a["records_with_chunks_added_by_the_layer"] = sum(1 for r in recs if (r.get("semantic") or {}).get("added_chunks"))
        # answer-level repeatability across the 3 runs (exact text)
        qids = sorted({k[1] for k in raw if k[0] == arm})
        a["questions_with_identical_answer_in_all_runs"] = sum(1 for q in qids if len({raw[(arm, q, r)]["answer"] for r in runs if (arm, q, r) in raw}) == 1)
        a["questions"] = len(qids)
        out["arms"][arm] = a
    p = h.RES / "partial_metrics_no_llm.json"
    p.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"wrote {p}")
    hdr = f"{'arm':14s} {'n':>4s} {'lat med/p95 s':>14s} {'out':>3s} {'ptok med':>8s} {'R@1':>6s} {'R@3':>6s} {'R@5':>6s} {'R@10':>6s} {'MRR':>6s} {'rowcov%':>8s} {'same-ans':>9s}"
    print(hdr)
    for arm, a in out["arms"].items():
        rd = a.get("retrieval_docq") or {}
        f = lambda x: "-" if x is None else f"{x:.3f}"
        rc = a.get("db_rowcov_pct_per_run")
        print(f"{arm:14s} {a['n']:4d} {a['latency_median_s']:6.2f}/{a['latency_p95_s']:<6.2f} {a['latency_outliers_excluded']:3d} {a['prompt_tokens_median'] or 0:8.0f} "
              f"{f(rd.get('R@1')):>6s} {f(rd.get('R@3')):>6s} {f(rd.get('R@5')):>6s} {f(rd.get('R@10')):>6s} {f(rd.get('MRR@10')):>6s} {(rr.mean(rc) if rc else '-')!s:>8s} "
              f"{a['questions_with_identical_answer_in_all_runs']}/{a['questions']}")


if __name__ == "__main__":
    main()
