# Audit: which stored results carry a stale `structured_status` (2026-11-15)

Context. `integration/structured_guard.py` (Person A, `5d11ae5`, 2026-10-31) catches `sqlite3.OperationalError: no such column: customer_id`
and does the msisdn mapping itself. Person B's `794662c` (2026-11-01 01:06 +0530) moved that into `structured/retriever.py::customer_scoped_filter`,
which never raises; the guard's success path then reports `executed=True, route="direct"` for every question. `794662c` reached Person A's
branches with the KG-hardening merge `abf055a` (2026-11-10 20:11 +0530, merging `700a5dd`). Everything below was read from the stored files
and the code at `a26ad49`; nothing was re-run or modified. Labels: VERIFIED (checked in the repo / counted in the file), REPORTED (someone
else's statement), INFERENCE.

## 1. Result sets

File mtimes under `data/experiments/` and `results/perf_report/` all read 2026-11-14 because the branch switch to `person-a/pinned-rerun`
re-checked those files out (e29f010 does not contain them); the dates below come from timestamps and manifests inside the files
(VERIFIED).

| result set | records | date (inside the file) | code state | before / after 2026-11-10 merge | `structured_status` stored? | affected? | evidence |
|---|---|---|---|---|---|---|---|
| `data/experiments/integrated_rag/20261013T183747Z_E14-subset.json` (E14a) | 10 per-query records | 2026-10-13 (file name; committed `fddcaa2` 2026-10-27) | before the guard existed (`5d11ae5` is 2026-10-31) and before `794662c` | before | no (`answer`, `factcheck`, `query_id`, `query_type`, `question`) | **no** | no guard, no status field; the retriever of that date raised on a customer-scoped msisdn-table query, so such a question could not have produced a record silently |
| `data/experiments/benchmark_base_vs_rag/` (`answers.jsonl`, `scores*.jsonl`, `benchmark_results.json`) | 1 per query | committed `fddcaa2` 2026-10-27 | before guard and `794662c` | before | no (`n_structured_results`, no status) | **no** | same as E14a |
| `data/experiments/parser_trial/before_integrate.json`, `after_trial.json` | 43 rows each | 2026-10-31 14:00 / 14:01 UTC | `a2faccf` / `394cd99` | before (guard active, retriever still raised) | `lookup_route` only: direct 40, msisdn_mapping 3 (both files) | **no** | the 3 msisdn_mapping rows show the guard working |
| `data/experiments/system_eval/abstention_test_20261031T142243Z_final_test.json`, `router_eval/*` | n/a | 2026-10-31 14:22 UTC (`00e451b`, tree dirty) | before `794662c` | before | no (`abstained`, `answer_text`, `final_route`, `reason`, ...) | **no** | produced through `integration/qa/system.py` while the guard still functioned |
| `results/perf_report/raw_answers.jsonl` (v3, 7 arms) | 948 (750 with a status; A, and routed-away records, carry `None`) | 2026-10-31 14:51 to 2026-11-01 14:31 UTC | manifest `2fdffad` (`integrate/kg-ontology-router-ui`), which does **not** contain `794662c` | before | yes | **no** (guard functional) | 18 records `route="msisdn_mapping"` (MH_RB_B02, 6 retrieval arms x 3 runs); 0 records `executed=False` |
| `results/kg_hardening_eval/raw_answers.jsonl` (B2, C_V0, C_V1, C_V1_links) | 504 | 2026-11-10 15:04 UTC onward | manifest `6f4f0fa` (contains `794662c`) | after | yes | **yes, metadata only** | 0 msisdn_mapping, 0 `executed=False`; MH_RB_B02 recorded `route="direct", customer_id=None, msisdn_lookup=None` with the **same** structured rows as v3 (`4996, 6256, 7127, 7144, 8967`) |
| `results/graph_merge_fix/raw_answers.jsonl` (GF, GFL) | 252 | 2026-11-11 11:04 UTC onward | manifest `afbbe8d` (contains `794662c`) | after | yes | **yes, metadata only** | same pattern as above |
| `results/final_ablation/` | no raw records (long run never started); `error_label_reconciliation.*`, `abstention_composition.*`, `failing_tests.md` only quote statuses from the sets above | 2026-11-11 | | after | derived | derived from the sets above; the abstention composition's "structured source empty" labels for MH01/MH04/MH05 are consistent with `executed=True` + 0 rows and would read the same with a working guard (see 4) | |

## 2. Distinct (executed, route, reason, note) combinations (VERIFIED by counting)

| result set | (True, direct, None, None) | (True, direct, None, "Query could not be confidently resolved...") | (True, msisdn_mapping, None, None) | status `None` | executed=False / not_executable |
|---|---|---|---|---|---|
| perf_report (v3) | 468 | 264 | 18 (MH_RB_B02 only) | 198 (A 126, router 36, C 36) | 0 / 0 |
| kg_hardening_eval | 282 (B2 75, C_V0 69, C_V1 69, C_V1_links 69) | 114 (B2 51, C arms 21 each) | 0 | 108 (C arms, routed away) | 0 / 0 |
| graph_merge_fix | 150 (GF 75, GFL 75) | 102 (51 each) | 0 | 0 | 0 / 0 |

Per retrieval arm in v3: B / B2 / docgraph / ontology 75 + 48 + 3; C / router 69 + 18 + 3; B_scifact_off 30 + 36 (22-question subset).

Tables that appear in any status: cdr, customer_master, escalation_cases, fiber_inventory, fraud_cases, invoices, kyc_records, network_alarms, orders,
payment_transactions, porting_requests, recharge_transactions, retail_outlets (v3 only), sim_inventory, subscriptions, tickets. No record in any set
carries Person B's notes "table has no customer key" or "unknown customer", and no v3 record (working guard) has `route="not_executable"`: the 42 questions
contain no customer-scoped lookup on a table without a customer key and no unknown customer (VERIFIED by absence in all three sets).

## 3. Where `structured_status` is consumed (VERIFIED, code at `a26ad49`)

| consumer | file:lines | what it does with it | could a wrong executed/route change... |
|---|---|---|---|
| measurement harness (v3, KG-hardening, merge-fix, final-ablation runs) | `eval/perf_report/harness.py:242` `rec["structured_status"] = self.pipeline.structured.last_status`; the prompt is built at :246-248 from `structured` rows + `top10` via `reciprocal_rank_fusion` / `build_context` / `generate_answer`, which never read the status | stored in the record | (d) only the logged metadata. (a)/(b)/(c) impossible: the status is not an input of fusion, context or generation. `integration/rag/context_builder.py`, `fuse.py`, `generate.py` contain no reference to it (grep). |
| error-cause rule | `eval/perf_report/run_report.py:327-333` `sql_retrieved()` reads `st.get("table")` and `structured_ids` | compares the needed table/row ids | no: `table` is `parsed.get("table")` on both guard paths; `executed`/`route` are not read |
| final-ablation diagnostics | `eval/final_ablation/fa_open_items.py:40-44` (abstention layer label text), `fa_reconcile.py:81` (`table` equality) | labels only | (d) only: the printed `executed=... route=...` in the abstention composition would read `msisdn_mapping` for MH_RB_B02 with a working guard; the layer decision uses `context_text`, not the status |
| E14 pipeline return value | `integration/rag/pipeline.py:276` `"structured_status": self.structured.last_status` | returned to callers | (d) |
| QA backend (app, abstention tests) | `integration/qa/retrieval.py:116-117` copies executed / reason / route / msisdn_lookup into `diag`; `integration/qa/system.py:208-215` sets `s_unexec = s_diag.get("executed") is False` and, on the structured route, replaces the answer with "The database lookup for this question could not be executed: {reason}."; `:254` appends "(the database part could not be executed: ...)" to an abstention reason; `:285` adds a `NOT ANSWERED: the database part ... could not be executed` line on the hybrid route; `:354-355` hybrid diagnostics | wording and the abstention decision depend on `executed` | (a)/(c) **in this path only**: with the stale guard `executed` is always True, so these branches cannot fire. They need `executed=False`, i.e. a customer-scoped lookup on a table with no customer key (Person B's code also returns no rows there, so the evidence is empty either way; what changes is the sentence, not the rows). No stored result was produced through this path after `794662c` (the abstention test is 2026-10-31 14:22 UTC). |
| QA backend KYC profile fallback | `integration/qa/retrieval.py:101-102` retries `customer_master` only when `lookup_status["route"] == "direct"` and the first lookup returned no rows | changes which rows are fetched | (b)/(c) possible in this path: with the stale guard an empty msisdn-mapped lookup (customer exists, no rows in cdr/recharge/sim) now reads `direct` and triggers the profile retry, which a working guard would have blocked. Same caveat: no stored result went through this path after `794662c`. |
| UI | `app/streamlit_app.py:161-162` renders the status | display | (d) |

## 4. The not-executable / unknown-customer wording (VERIFIED from code, see 3)

* Measurement harness: there is no wording. With a working guard the structured rows would be `[]`, exactly what Person B's retriever returns now, so
  the prompt text would be byte-identical; only `structured_status` in the record would differ (`executed=False, route="not_executable",
  reason="table '<t>' has no customer_id and no msisdn column, so a per-customer lookup cannot be run on it"` or `"... keyed by msisdn and
  customer_master has no row for this customer"`).
* QA backend: structured route -> answer "The database lookup for this question could not be executed: <reason>."; hybrid route -> normal answer plus
  "NOT ANSWERED: the database part of the question could not be executed (<reason>)"; abstention reason suffixed on the abstention path.
* Stored results: none of the 42 benchmark questions triggers either condition (0 such statuses in v3, where the guard worked), so no stored
  record shows or should show that wording. Whether the merged retriever would mark any benchmark question `executed=False` cannot be read from
  the stored files (the stale guard overwrote the flag); from the question set (no customer-scoped question on a key-less table) INFERENCE: none.

## 5. Conclusions

1. VERIFIED: E14a (2026-10-13) and the Base-vs-RAG benchmark (2026-10-27) are **not affected**: they predate the guard and the retriever change and
   store no status.
2. VERIFIED: v3 (`results/perf_report/`, 2026-10-31/11-01) ran with a working guard (`2fdffad` does not contain `794662c`); its statuses are correct.
3. VERIFIED: `results/kg_hardening_eval/` (2026-11-10) and `results/graph_merge_fix/` (2026-11-11) carry the stale status on every record
   (`executed=True, route="direct"`; 396 + 252 = 648 records carry a status). The only question where a working guard would have recorded something else
   is MH_RB_B02 (`route="msisdn_mapping"`; 3 runs x 6 arms = 18 records across the two sets: B2, C_V0, C_V1, C_V1_links, GF, GFL); its structured rows are identical to v3's, so the prompt,
   the answer and every reported metric are unaffected. The error-cause rule reads only `table` and the row ids. **Metadata only.**
4. VERIFIED: no stored record in any set was produced on a question where `executed=False` would apply.
5. The QA backend (`integration/qa/system.py`, the app and the abstention test path) is where a wrong `executed`/`route` *can* change an answer
   (wording, abstention reason, KYC profile fallback). No stored result went through it after `794662c`. INFERENCE: the app has been running with
   those branches dead since 2026-11-10.
6. Fix pending Person B's answers (`docs/reviews/guard_test_diagnosis.md`); not changed here.
