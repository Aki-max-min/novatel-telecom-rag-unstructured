# Final measurement: STATUS = INCOMPLETE (blocked by Ollama)

Written 2026-11-01. Nothing in this folder is a final result. Every number below was computed by code from the saved files named next to it.

## Done
* Preconditions (git clean at HEAD 8e86ea9; 158 tests passed 3 times, structured 29 passed, hybrid 181 passed / 1 skipped; all required fixes present).
* Question set: 42 verified questions, none dropped (`eval/perf_report/questions.jsonl`, `question_counts.json`, `review_gold.csv`).
* Determinism preflight (`determinism_check.json`): **only 4 of 10 questions gave identical answers across two identical runs (temperature 0, seed 42)**, so 3 runs per arm are required and reported as mean and range.
* Generation: arms **A, B, B2, router, ontology, docgraph, C are complete: 3 runs x 42 questions = 126 records each (882 records)**, all `cached=false`, SciFact filter on.
  The SciFact-off reproduction arm (`B_scifact_off`, original 22 questions x 3 runs = 66 records) has 2 of 66 records.
* LLM-free metrics (`partial_metrics_no_llm.json`): retrieval R@k / MRR, database-row coverage, latency, prompt tokens, routing counts.

## Not done (needs a working Ollama)
* 64 reproduction-arm generations.
* All judging: correctness (document, cross, multi), relevance, groundedness, hallucination, citation verification, judge-integrity re-judge and the human-review sample.
* Therefore: correctness / relevance / groundedness / hallucination / citation metrics, paired statistics, error analysis, regressions, ablation correctness, `values.json`, `human_review_sample.csv` do not exist yet.
  (`run_report.py` was dry-run on fabricated scores in a scratch folder only to test the code: 159 expected keys == 159 generated; nothing from that dry run is saved here.)

## Why it stopped
After repeated machine suspends during the run (log timestamps jump by up to ~12 h; latency outliers above 120 s are excluded from latency statistics), Ollama's model runner stayed in the
state `qwen2.5:7b-instruct ... Stopping...` for more than 15 minutes and every request timed out (tiny `ollama.chat` probes, 40-100 s limits). Ollama was started before this session and is not mine to
kill or restart, so the run was stopped here. My own processes (generation, probes) were stopped; none is running.

## To resume (exact commands, from the repo root; the first step is yours)
1. Restart Ollama: quit it from the system tray (or `taskkill /IM "ollama app.exe" /F` and `taskkill /IM ollama.exe /F`), start it again (`ollama serve` or the Start-menu app), then check
   `ollama run qwen2.5:7b-instruct "Say OK"` answers. Keep the machine awake (power settings: never sleep) until the run is finished.
2. `python eval/perf_report/run_generate.py generate --runs 3`        (skips the 884 finished records; runs the remaining 64)
3. `python eval/perf_report/run_score.py score`                         (judge + citation verification; resumable)
4. `python eval/perf_report/run_score.py integrity`                     (20% re-judge + `human_review_sample.csv`)
5. `python eval/perf_report/diagnose_false_abstentions.py`              (retrieval-only diagnosis of the 5 false abstentions)
6. `python eval/perf_report/run_report.py`                              (metrics.json, values.json, ablation.csv, error_table.csv, regressions.md)
The resume guard accepts later commits only if they touch nothing outside `eval/perf_report/` and `results/perf_report/`.
