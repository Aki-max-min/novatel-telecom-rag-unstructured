# Error-cause label reconciliation (v3 C vs KG-hardening C_V0)

Analysis only. The labelling rule (`eval/perf_report/run_report.classify`) is not changed here.

## 1. Which code produced which table

* **rule_file**: eval/perf_report/run_report.py (function classify, CAUSES, error_analysis)
* **v3_table_commit**: dc481b6 (Measurement 3/3; results/perf_report/error_table.csv and metrics.json written by this code)
* **kg_table_commit**: 6956902 (eval/kg_hardening_eval/run_report.py imports eval/perf_report/run_report.classify unchanged)
* **last_change_of_rule_file**: dc481b6 2026-11-01 Measurement (3/3): scoring, integrity, diagnostics and report complete (948 records scored, values.json 159 keys)
* **diff_dc481b6_HEAD_rule_file**: (empty: identical)
* **kg_call**: rr.classify('C' if arm in C_ARMS else 'B2', q, raw[key], scored[key], ref=B2 same run, scored B2)
* **v3_call**: classify(arm, q, raw[key], scored[key], ref=B2 same run if arm == 'C' else None, scored B2); B's router/graph remapped to model

## 2. The same current rule applied to both raw-answer sets

### v3 arm C: table on disk vs re-labelled now (reference: v3 B2 of the same run)

| arm (rule applied) | retrieval | context | competing | ranking | model | router | graph | scoring | total |
|---|---|---|---|---|---|---|---|---|---|
| v3 C, results/perf_report/error_table.csv | 12 | 6 | 3 | 6 | 9 | 12 | 3 | 0 | 51 |
| v3 C, classify() run now | 12 | 6 | 3 | 6 | 9 | 12 | 3 | 0 | 51 |

Answers whose label differs between the file and the re-labelling: 0 (the file is reproduced exactly).

v3 arm B: 0 label mismatches between file and re-labelling.

### KG-hardening arm C_V0: table on disk vs re-labelled now (reference: KG-hardening B2 of the same run)

| arm (rule applied) | retrieval | context | competing | ranking | model | router | graph | scoring | total |
|---|---|---|---|---|---|---|---|---|---|
| C_V0, results/kg_hardening_eval/error_table.csv | 9 | 9 | 3 | 6 | 9 | 12 | 3 | 0 | 51 |
| C_V0, classify() run now | 9 | 9 | 3 | 6 | 9 | 12 | 3 | 0 | 51 |

Answers whose label differs: 0 (the file is reproduced exactly).

### Side by side, same rule

| arm (rule applied) | retrieval | context | competing | ranking | model | router | graph | scoring | total |
|---|---|---|---|---|---|---|---|---|---|
| v3 C | 12 | 6 | 3 | 6 | 9 | 12 | 3 | 0 | 51 |
| C_V0 (KG-hardening run) | 9 | 9 | 3 | 6 | 9 | 12 | 3 | 0 | 51 |

## 3. Where the two C arms get different labels (same question, same run)

Answers with a different label: 12 of 126 pairs. Over all 126 (question, run) pairs, the raw records differ in: route 0, doc_top10 0, structured_ids 12, structured_status 6, prompt_docs 0, prompt_sql_rows 12, answer 77, added_chunks 0.
Correctness differs on 13 answers: [('RW_001', 1, 2, 1), ('MH_RB_B04', 1, 2, 0), ('MH_RB_B06', 1, 0, 1), ('MH12', 1, 1, 2), ('MH13', 1, 1, 2), ('RW_001', 2, 2, 1), ('MH_RB_B04', 2, 2, 0), ('MH12', 2, 1, 2), ('MH13', 2, 1, 2), ('RW_001', 3, 2, 1), ('MH_RB_B04', 3, 2, 0), ('MH12', 3, 1, 2), ('MH13', 3, 1, 2)]

| id | run | cat | v3 C label (corr.) | C_V0 label (corr.) | route same | doc_top10 same | SQL ids same | prompt docs same | prompt SQL rows same | answer same | v3 SQL ids -> C_V0 SQL ids |
|---|---|---|---|---|---|---|---|---|---|---|---|
| RW_001 | 1 | trai | - (-) | context (1) | True | True | True | True | True | False | [] -> [] |
| MH_RB_B04 | 1 | cross | - (-) | retrieval (0) | True | True | True | True | True | False | ['14212'] -> ['14212'] |
| MH12 | 1 | multi | retrieval (1) | - (-) | True | True | False | True | False | False | ['5001', '5002', '5003', '5004', '5005'] -> ['5001', '6001', '6002'] |
| MH13 | 1 | multi | retrieval (1) | - (-) | True | True | False | True | False | False | ['11011'] -> ['11011', '28248'] |
| RW_001 | 2 | trai | - (-) | context (1) | True | True | True | True | True | False | [] -> [] |
| MH_RB_B04 | 2 | cross | - (-) | retrieval (0) | True | True | True | True | True | False | ['14212'] -> ['14212'] |
| MH12 | 2 | multi | retrieval (1) | - (-) | True | True | False | True | False | False | ['5001', '5002', '5003', '5004', '5005'] -> ['5001', '6001', '6002'] |
| MH13 | 2 | multi | retrieval (1) | - (-) | True | True | False | True | False | False | ['11011'] -> ['11011', '28248'] |
| RW_001 | 3 | trai | - (-) | context (1) | True | True | True | True | True | False | [] -> [] |
| MH_RB_B04 | 3 | cross | - (-) | retrieval (0) | True | True | True | True | True | False | ['14212'] -> ['14212'] |
| MH12 | 3 | multi | retrieval (1) | - (-) | True | True | False | True | False | False | ['5001', '5002', '5003', '5004', '5005'] -> ['5001', '6001', '6002'] |
| MH13 | 3 | multi | retrieval (1) | - (-) | True | True | False | True | False | False | ['11011'] -> ['11011', '28248'] |

Detail strings (v3 C / C_V0):

* RW_001 run 1: v3 C `` ; C_V0 `docs_in_prompt=False sql_rows_in_prompt=True`
* MH_RB_B04 run 1: v3 C `` ; C_V0 `docs_retrieved=True sql_retrieved=False`
* MH12 run 1: v3 C `docs_retrieved=True sql_retrieved=False` ; C_V0 ``
* MH13 run 1: v3 C `docs_retrieved=True sql_retrieved=False` ; C_V0 ``
* RW_001 run 2: v3 C `` ; C_V0 `docs_in_prompt=False sql_rows_in_prompt=True`
* MH_RB_B04 run 2: v3 C `` ; C_V0 `docs_retrieved=True sql_retrieved=False`
* MH12 run 2: v3 C `docs_retrieved=True sql_retrieved=False` ; C_V0 ``
* MH13 run 2: v3 C `docs_retrieved=True sql_retrieved=False` ; C_V0 ``
* RW_001 run 3: v3 C `` ; C_V0 `docs_in_prompt=False sql_rows_in_prompt=True`
* MH_RB_B04 run 3: v3 C `` ; C_V0 `docs_retrieved=True sql_retrieved=False`
* MH12 run 3: v3 C `docs_retrieved=True sql_retrieved=False` ; C_V0 ``
* MH13 run 3: v3 C `docs_retrieved=True sql_retrieved=False` ; C_V0 ``

## 5. Reading

(filled in by hand in SUMMARY.md / STATUS.md from the numbers above; see the final report)