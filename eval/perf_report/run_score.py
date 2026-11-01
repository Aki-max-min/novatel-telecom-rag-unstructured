"""
Scoring stage. Reads results/perf_report/raw_answers.jsonl, appends one record per (arm, question, run) to results/perf_report/scored_answers.jsonl
(resumable: finished records are skipped, nothing is overwritten).

    python eval/perf_report/run_score.py score        # judge + deterministic checks + citation verification (B and C)
    python eval/perf_report/run_score.py integrity    # re-judge a random 20% (min 10) of document/cross/multi answers; export the human-review sample

Judge = the E14a judge: same local model as the generator, temperature 0, E14a prompts (integration/eval/base_vs_rag.py).
Citation verification = integration.qa.citations.verify_answer with QAConfig(verifier="nli"): every sentence must carry a valid [E#] id;
numbers must occur in the cited evidence; lexical stem overlap; NLI entailment (MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli, CPU) over 2-sentence
windows of the cited evidence. SUPPORTED >= 0.50 entailment, WEAK >= 0.15 (or lexical >= 0.60), otherwise UNSUPPORTED; a sentence with no valid citation is UNSUPPORTED.
It labels sentences; it never edits an answer.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402

from integration.qa.config import QAConfig  # noqa: E402

LOG = h.RES / "run_log.txt"
CITATION_ARMS = {"B", "C"}
INTEGRITY_ARMS = ["A", "B", "B2", "C"]
INTEGRITY_CATEGORIES = {"syn", "trai", "cross", "multi"}
INTEGRITY_SEED = 20261031
SECOND_JUDGE_MODEL = "qwen2.5:3b-instruct"


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class UncachedJudge(h.CachedJudge):
    def chat(self, system: str, user: str, uncached: bool = True) -> str:
        return super().chat(system, user, uncached=True)


def score(limit: int | None = None) -> None:
    qs = {q["id"]: q for q in h.load_questions()}
    done = {(r["arm"], r["id"], r["run"]) for r in h.read_jsonl(h.SCORED)}
    raw = [r for r in h.read_jsonl(h.RAW) if (r["arm"], r["id"], r["run"]) not in done]
    if limit:
        raw = raw[:limit]
    log(f"scoring {len(raw)} records ({len(done)} already scored)")
    judge = h.CachedJudge()
    cfg = QAConfig(verifier="nli")
    for i, rec in enumerate(raw, 1):
        q = qs[rec["id"]]
        sc = h.score_answer(q, rec, judge)
        if rec["arm"] in CITATION_ARMS:
            sc["citation"] = h.citation_check(rec, cfg)
        sc["scored_utc"] = datetime.now(timezone.utc).isoformat()
        h.append_jsonl(h.SCORED, sc)
        if i % 25 == 0 or i == len(raw):
            log(f"[{i}/{len(raw)}] {rec['arm']} {rec['id']} run{rec['run']} correctness={sc['correctness']} (judge calls {judge.calls}, cache hits {judge.hits})")


def integrity() -> dict:
    qs = {q["id"]: q for q in h.load_questions()}
    raw = {(r["arm"], r["id"], r["run"]): r for r in h.read_jsonl(h.RAW)}
    scored = [s for s in h.read_jsonl(h.SCORED) if s["arm"] in INTEGRITY_ARMS and s["category"] in INTEGRITY_CATEGORIES]
    n = max(10, round(0.20 * len(scored)))
    sample = random.Random(INTEGRITY_SEED).sample(sorted(scored, key=lambda s: (s["arm"], s["id"], s["run"])), n)
    log(f"integrity: re-judging {n} of {len(scored)} document/cross/multi answers (seed {INTEGRITY_SEED})")

    same = UncachedJudge()
    other = UncachedJudge(model=SECOND_JUDGE_MODEL)
    rows, agree_same, agree_other, bin_same, bin_other = [], 0, 0, 0, 0
    for s in sample:
        q, rec = qs[s["id"]], raw[(s["arm"], s["id"], s["run"])]
        r1 = h.score_answer(q, rec, same)
        r2 = h.score_answer(q, rec, other)
        a1, a2 = r1["correctness"] == s["correctness"], r2["correctness"] == s["correctness"]
        b1 = (r1["correctness"] == 2) == (s["correctness"] == 2)
        b2 = (r2["correctness"] == 2) == (s["correctness"] == 2)
        agree_same += a1; agree_other += a2; bin_same += b1; bin_other += b2
        rows.append({"arm": s["arm"], "id": s["id"], "run": s["run"], "category": s["category"], "original": s["correctness"],
                     "rejudge_same_model": r1["correctness"], "rejudge_second_model": r2["correctness"]})
    out = {"n_sample": n, "n_pool": len(scored), "seed": INTEGRITY_SEED, "arms": INTEGRITY_ARMS,
           "same_model_uncached_rejudge": {"model": h.DEFAULT_MODEL, "exact_agreement": f"{agree_same}/{n}", "agreement_fully_correct_vs_not": f"{bin_same}/{n}"},
           "second_model_rejudge": {"model": SECOND_JUDGE_MODEL, "exact_agreement": f"{agree_other}/{n}", "agreement_fully_correct_vs_not": f"{bin_other}/{n}"},
           "reading": "same-model agreement measures the judge's own repeatability at temperature 0 (decoding is not fully deterministic on this machine); "
                      "second-model agreement is a rough independence check, not a validity measure -- only a human review of the exported sample is.",
           "rows": rows}
    (h.RES / "judge_integrity.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    with open(h.RES / "human_review_sample.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arm", "question_id", "run", "category", "question", "answer", "reference_excerpt", "judge_correctness_0_1_2", "judge_relevance",
                    "human_verdict_correct_0_1_2", "human_notes"])
        for s in sample:
            q, rec = qs[s["id"]], raw[(s["arm"], s["id"], s["run"])]
            w.writerow([s["arm"], s["id"], s["run"], s["category"], q["query"], rec["answer"][:1500], h.reference_text(q)[:700].replace("\n", " "),
                        s["correctness"], s.get("relevance"), "", ""])
    log(f"integrity: same-model exact agreement {agree_same}/{n}, second-model {agree_other}/{n}; sample exported")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["score", "integrity"])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    score(args.limit) if args.stage == "score" else integrity()


if __name__ == "__main__":
    main()
