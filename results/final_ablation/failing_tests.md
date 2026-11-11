# The 6 failing tests on the merged branch (analysis only; nothing fixed)

Run 2026-11-11 with `.venv_colpali/Scripts/python.exe -m pytest integration/tests/test_rag_defaults_identical.py integration/tests/test_structured_guard.py`
(log: `failing_tests_pytest.log`): 6 failed, 8 passed. Both test files are Person A's; every failure is caused by Person B's structured-side
changes that arrived with the `person-b/kg-hardening` merge (`abf055a`), none by the KG hardening itself and none by Person A's code.

| # | test | exact failure | origin | source commit(s) |
|---|---|---|---|---|
| 1 | `test_rag_defaults_identical.py::test_default_prompts_identical_to_head` | `prompt evidence changed for: ['Q04']` (sha256 of the default-config prompt context differs from the golden file recorded at HEAD bf41951 for 1 of 22 E14a questions) | **parser branch**: for "Why is my latest postpaid bill higher than usual?" the old substring parser returned invoice rows 5001/5002/5004; the merged parser returns no structured result (status note "Query could not be confidently resolved to structured data"), so the prompt holds different blocks | `structured/query_parser.py`: `2f365ea` (word-boundary keyword matching, ambiguous ties return no table) and `478256f` (keyword-strength weights), both Daksh1509 (Person B), merged via `person-b/parser-tiers-msisdn` into `person-b/kg-hardening`. The test and fixture are Person A's (`711d205`). |
| 2 | `test_structured_guard.py::test_msisdn_keyed_table_is_answered_through_the_customers_msisdn` | `status["route"] == 'direct'`, expected `'msisdn_mapping'` (rows ARE returned: `expected > 0` holds) | **parser branch (structured retriever)**: Person B's `StructuredRetriever.customer_scoped_filter` now maps msisdn-keyed tables through `customer_master` itself and returns rows with `metadata["route"] = "msisdn_mapping"`; Person A's guard (`integration/structured_guard.py`) only takes its own `msisdn_mapping` path when the retriever cannot execute, so it now reports the retriever's success as `direct` | `structured/retriever.py` `794662c` ("customer-scoped lookups map msisdn-keyed tables via customer_master; never raise, never unscoped", Daksh1509). Guard and tests: Person A `5d11ae5`. |
| 3 | `test_structured_guard.py::test_table_with_no_customer_or_msisdn_column_is_reported_not_executable[network_sites]` | `status["executed"] is True`, expected `False` with route `not_executable` (results are `[]` as expected) | same as 2: the retriever now returns an executed, empty result with a note instead of raising, so the guard's not-executable branch is not reached | `794662c` |
| 4 | `test_structured_guard.py::test_table_with_no_customer_or_msisdn_column_is_reported_not_executable[offers]` | same as 3 | same as 3 | `794662c` |
| 5 | `test_structured_guard.py::test_unknown_customer_on_an_msisdn_table_is_reported_with_the_reason` | `status["executed"] is True`, expected `False` with reason containing "customer_master has no row" | same mechanism: the unknown-customer case is handled inside the retriever ("never raise") and surfaces as an executed empty result | `794662c` |
| 6 | `test_structured_guard.py::test_e14_adapter_uses_the_guard_and_exposes_the_status` | `StructuredSearchAdapter.last_status["route"] == 'direct'`, expected `'msisdn_mapping'` | same as 2, seen through the E14 adapter (`integration/rag/pipeline.py::StructuredSearchAdapter`) | `794662c` |

## What this means for the measurements

* Failure 1 is the parser effect already reported as the separate B2-new vs B2-v3 line: it affects every arm on this branch equally and is
  why A, B and B2 are (re)measured on this branch. The new parser raises database-row coverage from 89.2% to 93.8% on the 42 questions; on Q04 it
  returns no rows where the old one returned three invoice rows that the E14a judge did not need (Q04 is a document question; B2 scores 2 on it).
* Failures 2 to 6 are a status-contract mismatch, not a lost answer: rows are returned through the customer's msisdn in both versions; only
  `status["route"]` / `status["executed"]` differ, and the harness records `structured_status` for information only (`classify` uses `table`
  and the retrieved ids, not `route`). No arm's retrieval or prompt depends on these fields.

## Who should change what (not done here)

* Tests 2 to 6 encode Person A's guard contract from before `794662c`. Either the guard is reduced to a pass-through now that the retriever
  owns the msisdn mapping (and the tests updated to the retriever's status), or Person B's retriever exposes `route` / `executed` / `reason` in
  the guard's vocabulary. This needs both people to agree on the status contract; it is not a one-sided fix.
* Test 1's golden file was recorded on the old parser. Re-recording it on the merged parser is a deliberate decision (it freezes the new
  parser's Q04 behaviour as "correct"); it should be taken together with Person B, not silently.
