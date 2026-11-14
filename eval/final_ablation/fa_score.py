"""
Scoring stage of the final ablation: the v3 judge (eval/perf_report/harness.py: score_answer + citation_check) on every record of
results/final_ablation/raw_answers.jsonl, appended to scored_answers.jsonl (resumable; finished records skipped; nothing overwritten).

    .venv_colpali/Scripts/python.exe eval/final_ablation/fa_score.py score

Every generated arm is judged at the full level (correctness, relevance, hallucination vs reference evidence, groundedness, hallucination
vs retrieved context). Arm A has no retrieved context, so score_answer leaves groundedness / halluc_ctx None (v3 behaviour) and the
citation check is not run for it (recorded as {"checked": false, "reason": "no retrieval (arm A)"}): those metrics are n/a for A.
The judge's prompt cache is seeded read-only from the v3 and KG-hardening caches; new verdicts go to results/final_ablation/judge_cache.jsonl.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_fa as fa  # noqa: E402

h = fa.h
from integration.qa.config import QAConfig  # noqa: E402

log = fa.log


def score(limit: int | None = None) -> None:
    qs = {q["id"]: q for q in h.load_questions()}
    done = {(r["arm"], r["id"], r["run"]) for r in h.read_jsonl(fa.SCORED)}
    raw = [r for r in h.read_jsonl(fa.RAW) if (r["arm"], r["id"], r["run"]) not in done]   # file order: arm -> run -> question
    if limit:
        raw = raw[:limit]
    log(f"scoring {len(raw)} records ({len(done)} already scored)")
    judge = fa.Judge()
    cfg = QAConfig(verifier="nli")
    started, n_ok, n_fail = time.time(), 0, 0
    for i, rec in enumerate(raw, 1):
        q = qs[rec["id"]]
        try:
            sc = h.score_answer(q, rec, judge)
            sc["citation"] = {"checked": False, "reason": "no retrieval (arm A)", "n_sentences": 0} if rec["arm"] == "A" else h.citation_check(rec, cfg)
        except Exception as exc:  # noqa: BLE001  -- record the failure and carry on
            n_fail += 1
            h.append_jsonl(fa.FAILURES, {"stage": "score", "arm": rec["arm"], "id": rec["id"], "run": rec["run"], "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                                         "timestamp_utc": datetime.now(timezone.utc).isoformat()})
            log(f"FAILED {rec['arm']} {rec['id']} run{rec['run']}: {type(exc).__name__}: {str(exc)[:120]} (recorded in failures.jsonl; continuing)")
            continue
        sc["scored_utc"] = datetime.now(timezone.utc).isoformat()
        h.append_jsonl(fa.SCORED, sc)
        n_ok += 1
        if i % 10 == 0 or i == len(raw):
            elapsed = time.time() - started
            eta = elapsed / i * (len(raw) - i)
            log(f"HEARTBEAT [{i}/{len(raw)}] ok={n_ok} failed={n_fail} {rec['arm']} {rec['id']} run{rec['run']} correctness={sc['correctness']} "
                f"(judge calls {judge.calls}, cache hits {judge.hits}, of which seeded caches {judge.seed_hits}) ETA {eta / 60:.0f} min")
    log(f"scoring done: ok={n_ok} failed={n_fail}; judge calls {judge.calls}, cache hits {judge.hits} (seeded caches {judge.seed_hits})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["score"])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    score(args.limit)


if __name__ == "__main__":
    main()
