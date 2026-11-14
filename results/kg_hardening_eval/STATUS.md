# STATUS: KG-hardening evaluation (Person B's hardened graph in Person A's pipeline)

Branch `exp/kg-hardening-eval`; written 2026-11-10 (UTC) after the report stage. Nothing was pushed; no history was rewritten.

## What ran (in this order)

| step | what | result |
|---|---|---|
| 0 | git safety: status recorded, branch `exp/kg-hardening-eval` created, `git merge --no-ff 700a5dd` (tip of `origin/person-b/kg-hardening`; the handoff commit `83a8aa7` is its ancestor; the 8 extra commits touch only Person B's `hybrid/` link-decoupling code, tests and docs) | merged as `abf055a`; only conflict `.gitignore`, both appended blocks kept |
| 1 | mapping of the four configurations to exact settings, V0 reproducibility check, frozen-harness check | `PRE_DECLARATION.md` (committed `7880b0e`, before any evaluation run) |
| 2 | `python -m knowledge_graph.build_related_aliases`, `python -m knowledge_graph.graph_builder`, `python -m hybrid.setup_check` with `.venv_colpali` | all three passed; logs `setup_logs/11_*.log`, `12_*.log`, `13_*.log`; 47 of 84 RELATED_TO links resolve, 37 unresolved listed in `setup_logs/06_related_links_resolution.txt`; `setup_logs/graph_rebuild_check.json`: non-RELATED_TO edges and non-stub nodes identical to the graph v3 used |
| 3 | pre-declaration committed before the smoke test | `7880b0e` |
| 4a | Ollama health check | `health.json`: `qwen2.5:7b-instruct` Q4_K_M, digest `845dbda0...`, probe OK |
| 4b | smoke test: 3 questions x 4 arms (run 1) + no-LLM retrieval comparison of the three C layers on all 42 questions | `smoke_test.json`: every record's arm label matches its layer settings; V1 changes retrieval vs V0 on 23 of 42 questions (all 23 with positive gate weight); links change 14 -> proceed |
| 4c | generation, 4 arms x 42 questions x 3 runs, order arm -> run -> question, answer cache OFF | 504/504 records, 0 failures, 0 router errors, 0 latency records flagged (gap > 600 s or slow > 120 s), max latency 15.9 s, 2379 s wall clock (15:04-15:44 UTC); `run_manifest.json` written on a clean tree at `6f4f0fa` |
| 4d | scoring, every arm at the full judge level + citation check | 504/504 scored, 0 failures (15:44-17:18 UTC); 354 new judge calls, 1182 cache hits of which 576 from the read-only v3 cache; new verdicts in `judge_cache.jsonl` only |
| 5 | report stage | `metrics.json`, `comparison_table.md`, `error_table.csv`, `per_question_scores.csv`, `graph_diagnostics.md` / `.json` |

## Oddities and things that went wrong (reported, not worked around silently)

1. **Wrong interpreter on the first setup attempt.** `python -m knowledge_graph.graph_builder` failed with `ModuleNotFoundError: networkx` because the shell's `python` is the system Python 3.12 without the project packages. `.venv_colpali` holds the package set recorded in the v3 manifest; the three setup commands were re-run unchanged with it and passed. Nothing was installed (`setup_logs/README.md`, first-attempt logs `01-03`).
2. **Six pre-existing test failures on the merged branch** (390 passed, 1 skipped): the default-config golden-prompt test fails on Q04 (the merged parser returns no structured rows where the v3 parser returned invoice rows 5001/5002/5004) and 5 tests in `integration/tests/test_structured_guard.py` (route `direct` instead of `msisdn_mapping`). They come from Person B's structured-side changes, affect every arm equally, and are the reason B2 was re-run on this branch. Not fixed here (`setup_logs/17_*`, `18_*`).
3. **First `generate` launch refused by the harness's own clean-tree check**: the health stage wrote `health.json` / `run_log.txt` before the manifest's dirty-tree check ran. Fixed by probing first and writing after the manifest (`6f4f0fa`); relaunched; no generation had happened before the refusal.
4. **Report stage crashed on partial data** (CI `None` when no scored pairs existed yet) while scoring was still running; guard added (`14c47ec`). The final report ran on complete data.
5. **`*.log` is git-ignored** in this repository, so the setup logs and the stdout logs were force-added (`git add -f`) as evaluation artifacts.
6. **Alias files showed as modified after the rebuild** only because of CRLF/LF (autocrlf); content identical.
7. **Lid-close / sleep**: `powercfg` shows sleep-after 0 and hibernate-after 0 on AC and the machine was on AC; the lid-close action is not readable without admin rights, so it is unconfirmed. No gap or slow record was flagged, so no sleep interrupted the runs.
8. **MH_RB_B01 / MH_RB_B04 in the hybrid route** show `sql_retrieved=False` in some arms/runs although document retrieval is identical across runs: the structured half of the hybrid route is not deterministic across runs (C_V1_links on MH_RB_B01: run 1 = 2, runs 2-3 = 0). Recorded as observed; not attributable to the graph with certainty.

## Skipped (not run)

* The v3 judge-integrity re-judge (a second uncached judging pass) was not run; the judge is the same model, temperature 0, seed 42, with 576 verdicts taken verbatim from the v3 cache.
* Person B's `links_enabled` / link-fusion path in `hybrid/` was not evaluated (per instruction; our four arms only).
* No parameter was tuned; each configuration ran exactly once (3 runs = the fixed protocol).

## Constraints honoured

* `results/perf_report/` untouched (read only). The 42 questions, gold, judge prompts, scoring code and seeds unchanged.
* Router calibration (threshold 0.5, incident routing) untouched; 0 router errors.
* Person B's files read-only except the artifacts produced by the three setup commands (`knowledge_graph/output/graph.json`, alias files; the alias files are byte-identical modulo line endings).
* No push, no force, no reset, no history rewrite.
