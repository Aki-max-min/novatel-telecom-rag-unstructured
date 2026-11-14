"""
Time estimate for the remaining measurement work (read-only apart from results/perf_report/time_estimate.json).

    python eval/perf_report/estimate_time.py

Times 5 real generations (the first 5 missing records of the reproduction arm; NOT written to raw_answers.jsonl), 10 real judge calls (uncached, E14a prompts, on
existing answers) and 3 citation verifications, then multiplies by the exact number of calls the scorer will make (h.planned_judge_calls).
Estimates, not measurements of the final run: the machine's speed, a warm model and prompt length all move them.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402

from integration.qa.config import QAConfig  # noqa: E402

OUT = h.RES / "time_estimate.json"


class TimedJudge:
    """Uncached judge that records the wall time of every call (so the cache and the cache file are untouched)."""

    def __init__(self):
        self.client = h.TimeoutClient(model=h.DEFAULT_MODEL)
        self.times: list[float] = []

    def chat(self, system: str, user: str, uncached: bool = True) -> str:
        t = time.time()
        out = self.client.chat(system=system, user=user)
        self.times.append(time.time() - t)
        return out


def main() -> None:
    qs = {q["id"]: q for q in h.load_questions()}
    raw = h.read_jsonl(h.RAW)
    done = {(r["arm"], r["id"], r["run"]) for r in raw}

    # ---- 5 generations ---------------------------------------------------------------------------------------------------------------------
    rig = h.Rig()
    missing = [(h.REPRO_ARM, q, run) for run in (1, 2, 3) for q in qs.values() if q["is_core"] and (h.REPRO_ARM, q["id"], run) not in done]
    gen_times = []
    for arm, q, run in missing[:5]:
        t = time.time()
        rig.generate(arm, q, run)
        gen_times.append(time.time() - t)

    # ---- 10 judge calls (real score_answer calls on existing answers of the full-level arms) -------------------------------------------------
    judge = TimedJudge()
    sample = [r for r in raw if r["arm"] in ("B", "C") and r["run"] == 1 and qs[r["id"]]["category"] in ("syn", "trai", "cross")][:6]
    for rec in sample:
        h.score_answer(qs[rec["id"]], rec, judge)
        if len(judge.times) >= 10:
            break
    judge_times = judge.times[:10]

    # ---- 3 citation verifications (NLI on CPU) -------------------------------------------------------------------------------------------------
    cfg = QAConfig(verifier="nli")
    cit_times = []
    for rec in [r for r in raw if r["arm"] == "C" and r["run"] == 1][:3]:
        t = time.time()
        h.citation_check(rec, cfg)
        cit_times.append(time.time() - t)

    g, j, c = statistics.mean(gen_times), statistics.mean(judge_times), statistics.mean(cit_times)

    # ---- counts ------------------------------------------------------------------------------------------------------------------------------
    all_recs = list(raw) + [{"arm": a, "id": q["id"], "run": run, "abstained": False} for a, q, run in missing]
    planned = {}
    for rec in all_recs:
        planned.setdefault(h.priority_tier(rec["arm"], qs[rec["id"]], rec["run"]), []).append(h.planned_judge_calls(qs[rec["id"]], rec))
    tiers = {}
    for t, calls in sorted(planned.items()):
        tiers[t] = {"records": len(calls), "judge_calls": sum(calls), "hours": round(sum(calls) * j / 3600, 2)}
    n_cit = sum(1 for r in raw if r["arm"] in ("B", "C"))
    pool = sum(1 for r in raw if r["arm"] in ("A", "B", "B2", "C") and qs[r["id"]]["category"] in ("syn", "trai", "cross", "multi"))
    n_int = max(10, round(0.20 * pool))
    int_calls = sum(h.planned_judge_calls(qs[r["id"]], r) for r in raw if r["arm"] in ("A", "B", "B2", "C") and qs[r["id"]]["category"] in ("syn", "trai", "cross", "multi")) \
        * n_int / max(pool, 1)
    est = {"generated_utc": datetime.now(timezone.utc).isoformat(),
           "measured": {"generation_s": [round(x, 1) for x in gen_times], "generation_mean_s": round(g, 1), "judge_call_s": [round(x, 1) for x in judge_times],
                        "judge_call_mean_s": round(j, 1), "citation_verification_s": [round(x, 1) for x in cit_times], "citation_mean_s": round(c, 1)},
           "counts": {"missing_repro_generations": len(missing), "judge_calls_by_tier": tiers, "judge_calls_total": sum(t["judge_calls"] for t in tiers.values()),
                      "citation_verifications": n_cit, "integrity_records": n_int, "integrity_judge_calls_each_model_approx": round(int_calls)},
           "estimate_hours": {"generate_missing_repro": round(len(missing) * g / 3600, 2), "judge_all": round(sum(t["judge_calls"] for t in tiers.values()) * j / 3600, 2),
                              "citation_all": round(n_cit * c / 3600, 2), "integrity": round(int_calls * 2 * j / 3600, 2)}}
    est["estimate_hours"]["total"] = round(sum(est["estimate_hours"].values()), 2)
    est["decision_threshold_hours"] = 4
    est["scope_decision"] = ("full run (estimate <= 4 h)" if est["estimate_hours"]["total"] <= 4 else
                             "priority order (estimate > 4 h): tier 0 reproduction, tier 1 original 22 x A/B/B2/C x 3 runs, tier 2 new 20 x A/B/B2/C x 3 runs, "
                             "tier 3 ablation arms run 1 only, tier 4 ablation runs 2-3 only if time allows")
    OUT.write_text(json.dumps(est, indent=2), encoding="utf-8")
    print(json.dumps(est, indent=2))


if __name__ == "__main__":
    main()
