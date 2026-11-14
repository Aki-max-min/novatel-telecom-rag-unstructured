# Final measurement: STATUS = COMPLETE (all 948 records generated and scored; human review of the judge not done)

Updated 2026-11-01. Every number below was computed by code from the saved files named next to it. Nothing was pushed.

## What ran
| Stage | Command | Result |
|---|---|---|
| Health check | `ollama ps` + one `qwen2.5:7b-instruct` request | answered in 4.99 s |
| Time estimate | `python eval/perf_report/estimate_time.py` -> `time_estimate.json` | 2.07 h estimated (below the 4 h threshold), so the **full** plan ran; no priority-order cut was needed |
| Generation | `run_generate.py generate --runs 3` | 64 missing reproduction records added: 948 records (7 arms x 126 + `B_scifact_off` 66), 0 failures |
| Scoring | `run_score.py score` | 948 of 948 scored, 0 failures (about 97 min, dominated by the NLI citation verifier on the B and C answers) |
| Integrity | `run_score.py integrity` | 65 of 324 answers re-judged (see below) |
| Diagnostics | `diagnose_false_abstentions.py`, `diagnose_graph_router.py` | `false_abstentions.json`, `diagnostics_graph_router.json` |
| Sensitivity | `sensitivity_s15.py` | `sensitivity_s15.json` (headline values unchanged) |
| Report | `run_report.py` | `values.json` 159 keys == 159 expected, none missing, none extra, none empty; `metrics.json`, `error_table.csv`, `ablation.csv`, `regressions.md` |

`failures.jsonl` does not exist: no call failed after the 300 s timeout and 2 retries. Latency statistics exclude 10 records (8 with a gap of more than 10 minutes since the previous record, 2 slower than 120 s); the per-arm counts are in `metrics.json`.

## Aggregation rule (as specified)
Temperature 0 with seed 42 is NOT deterministic on this machine (4 of 10 questions gave identical answers in the preflight), so every arm ran 3 times. The headline per-arm correctness is the **mean of the three per-run accuracies, with the min-max range in `metrics.json`**. Paired statistics: bootstrap CI on the per-question correct-fraction across runs (questions resampled, 10,000 resamples, seed 20261031); exact McNemar on majority-vote correctness (correct if at least 2 of 3 runs fully correct). Run-to-run variability per arm is in `metrics.json` (`arms.<arm>.variability`).

## Known limits (not hidden)
* **Judge**: the same local 7B model generates and judges. Uncached same-model re-judge agreed on 63 of 65 sampled answers; the second judge (`qwen2.5:3b-instruct`) agreed on only 42 of 65 (48 of 65 on fully-correct vs not). `human_review_sample.csv` has the 65 rows for a human verdict; the "human verdict" column is empty, so no human validation exists.
* **S15 scoring artifact**: the router arm and arm C answer the gibberish query S15 with the system's standard abstention message, which E14a's fixed phrase list does not contain, so it scored 0 (3 records each). This was not changed in the headline; `sensitivity_s15.json` shows the effect (router 76.2 -> 78.6, C 67.5 -> 69.8).
* The structured KG is not wired into retrieval and was not run (`not run (not wired into retrieval)`).
* The 20 new questions: multi, cross and held-out db questions were written/derived by Claude Code and are unreviewed by a human (see `values.json: review_status_new`).
* `partial_metrics_no_llm.json` is the earlier LLM-free summary and uses an older latency-exclusion rule; `metrics.json` supersedes it.

## Files
`raw_answers.jsonl` (948), `scored_answers.jsonl` (948), `judge_cache.jsonl`, `judge_integrity.json`, `human_review_sample.csv`, `metrics.json`, `values.json`, `error_table.csv`, `ablation.csv`, `regressions.md`, `false_abstentions.json`, `diagnostics_graph_router.json`, `sensitivity_s15.json`, `time_estimate.json`, `run_manifest.json`, `run_log.txt`, `determinism_check.json`.
