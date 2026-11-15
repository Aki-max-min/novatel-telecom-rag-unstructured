# Guard-test diagnosis on `person-a/pinned-rerun` (86d2802), 2026-11-15

Read-only diagnosis of the six pre-existing test failures (five in `integration/tests/test_structured_guard.py`, one in
`integration/tests/test_rag_defaults_identical.py`). Nothing was fixed. Interpreter `.venv_colpali`; full output saved in the session
scratchpad (`guard_pinned.log`, `guard_0395c5a.log`). Every statement is labelled VERIFIED (checked in the repo / by running it),
REPORTED (Person B's statement, not checked) or INFERENCE.

## Root cause in one paragraph (VERIFIED)

`integration/structured_guard.py` (Person A, commit `5d11ae5`, 2026-10-31) works by **catching**
`sqlite3.OperationalError: no such column: customer_id` from `StructuredRetriever.search` and then doing the msisdn mapping / the
"not executable" verdict itself. Person B's commit `794662c` (2026-11-01, "customer-scoped lookups map msisdn-keyed tables via
customer_master; never raise, never unscoped") moved that logic **into** `structured/retriever.py::customer_scoped_filter`, which
`exact_filter(..., "customer_id", ...)` now always calls. The retriever therefore never raises, the guard's `try` branch always
succeeds, and the guard reports `executed=True, route="direct"` for every question, ignoring the `executed` / `route` / `note` keys
the retriever now puts in its result dict. The guard's second half (mapping, reasons) is dead code on this branch. Both sides
implement the same idea; the status contract between them was never reconciled.

Probe (VERIFIED, `structured/retriever.py` blob `cc48ede`, identical on 0395c5a, e29f010 and 86d2802):

| question | parser | `retriever.search` returns | guard status returned |
|---|---|---|---|
| Show recharge transactions for customer 1056 | `recharge_transactions`, exact_filter on customer_id=1056 | 5 rows, `executed=True`, `route="msisdn_mapping"`, each row `metadata.route="msisdn_mapping"` | `executed=True, route="direct", reason=None, msisdn_lookup=None` |
| Show network sites for customer 1056 | `network_sites`, customer_id=1056 | 0 rows, `executed=False`, no `route`, `note="table has no customer key; cannot scope to a customer"` | `executed=True, route="direct", note=<that note>` |
| Show offers for customer 1056 | `offers`, customer_id=1056 | same as above | same as above |
| Show recharge transactions for customer 99999 | `recharge_transactions`, customer_id=99999 | 0 rows, `executed=True`, `note="unknown customer; nothing to scope to"` | `executed=True, route="direct"` |

## Per-test table

| test | expected (assertion) | actual | owner | evidence |
|---|---|---|---|---|
| `test_msisdn_keyed_table_is_answered_through_the_customers_msisdn` | `g.status["executed"] and g.status["route"] == "msisdn_mapping"`; `g.parsed["filter_column"] == "msisdn"`; `g.status["msisdn_lookup"]["filter_value"] == msisdn` | `route == "direct"` (`AssertionError: assert (True and 'direct' == 'msisdn_mapping'`); rows ARE the 5 msisdn-mapped rows (retriever did the mapping itself) | **my adapter code** (ii) | VERIFIED: the retriever reports `route="msisdn_mapping"` at the top level of its result and on every row's metadata; the guard discards it and hard-codes `"direct"` on the success path. The data is right, the status is not. |
| `test_table_with_no_customer_or_msisdn_column_is_reported_not_executable[network_sites]` | `g.results == [] and g.status["executed"] is False and g.status["route"] == "not_executable"`; `"no customer_id and no msisdn" in reason` | `executed is True` (`assert ([] == [] ... and True is False)`); retriever said `executed=False`, note "table has no customer key; cannot scope to a customer" | **my adapter code** (ii) for `executed`; **wording** differs from Person B's note (the test's phrase "no customer_id and no msisdn" is the guard's own text) | VERIFIED: retriever returns `executed=False` + note; guard overwrites with `executed=True`. If the guard adopted the retriever's status, the `executed` / `route` parts pass; the substring check would still fail unless the guard keeps its own wording or the test accepts Person B's note. |
| `...not_executable[offers]` | same | same | same | same |
| `test_unknown_customer_on_an_msisdn_table_is_reported_with_the_reason` | `g.status["executed"] is False and "customer_master has no row" in reason` | `executed is True` (`assert (True is False)`); retriever returned `executed=True`, 0 rows, note "unknown customer; nothing to scope to" | **contract disagreement with the structured side** (iii), plus (ii) | VERIFIED: `customer_scoped_filter` deliberately returns `executed=True` for an unknown customer (`empty("unknown customer; nothing to scope to", True)`): "the lookup ran and found nobody". My guard/test treat it as not executable ("customer_master has no row for this customer"). Both are defensible; it is a semantic decision, not a bug. INFERENCE: Person B's choice means a wrong customer id is indistinguishable from a customer with no rows unless the caller reads `note`. |
| `test_e14_adapter_uses_the_guard_and_exposes_the_status` | `a.last_status["route"] == "msisdn_mapping"`; second query `== []` and `last_status["executed"] is False` | `'direct' == 'msisdn_mapping'` fails at the first assertion | **my adapter code** (ii) | VERIFIED: `StructuredSearchAdapter.search` copies `guarded.status`, so it inherits the guard's wrong `route` / `executed`. Nothing in `integration/rag/pipeline.py` itself is at fault. |
| `test_default_prompts_identical_to_head` | `assert not mismatches` (22 E14a golden prompts, sha256 of context text + evidence ids) | `prompt evidence changed for: ['Q04']` | **Person B's parser change** (iii), reported as expected | VERIFIED: 21 of 22 prompts identical; only Q04 differs. Q04 = "Why is my latest postpaid bill higher than the monthly rental I expected to pay?". Golden evidence: structured `5001`, `5002`, `5004` (invoices) interleaved with the FAQ_C04_007 chunks. Old parser at `dc481b6` returned `{'table': 'invoices', 'method': 'exact_filter', 'filter_column': 'payment_status', 'filter_value': 'Paid'}` ("paid" matched inside "postpaid"); the merged parser (blob `6d3b83c`, identical on all three commits) returns `{'table': 'invoices', 'method': 'exact_filter_unresolved', 'error': 'No specific filter identified'}` and the retriever returns no rows ("Query could not be confidently resolved to structured data"). No other prompt changed. |

Owner key: (i) test wrong/stale, (ii) my adapter/integration code, (iii) structured side (Person B).

## Do the failures also occur on the pre-merge commits? (VERIFIED)

| commit | what | result |
|---|---|---|
| `86d2802` person-a/pinned-rerun | both files, `.venv_colpali` | 6 failed / 8 passed (43.6 s) |
| `0395c5a` exp/kg-hardening-eval (temporary detached worktree) | same files, same interpreter | **6 failed / 8 passed (31.0 s), the same six tests, same assertion messages** (`'direct' == 'msisdn_mapping'`, `True is False`, `['Q04']`) |
| `e29f010` origin/person-b/kg-fixes6 (temporary detached worktree) | — | **not applicable**: `integration/structured_guard.py`, `integration/rag/pipeline.py` and both test files do not exist at e29f010 (its `integration/` holds only `__init__.py`, `tests/`, `unstructured_adapter.py`). `structured/retriever.py` and `structured/query_parser.py` are byte-identical to 0395c5a (blobs `cc48ede`, `6d3b83c`), so the structured behaviour that causes the failures is the same there. |

Consequence: the kg-fixes6 merge changed nothing about these tests (`git diff 0395c5a 86d2802 -- structured/ integration/ query_router/` is empty). The failures date from the KG-hardening merge of `700a5dd` (2026-11-10) and were already listed in `results/kg_hardening_eval/STATUS.md` item 2. Both worktrees were removed afterwards (`git worktree list` shows only the main checkout).

## Effect on measurements (INFERENCE unless stated)

* Every arm of the KG-hardening, graph-merge-fix and (planned) final-ablation runs goes through `StructuredSearchAdapter`, so the **rows** a
  customer-scoped question gets are Person B's mapped rows (VERIFIED: `test_the_observed_failing_benchmark_question_now_runs` passes), but
  `structured_status` recorded in those runs says `route="direct"` and `executed=True` for every question. Any abstention or
  "could not be executed" wording that depends on `executed=False` has not fired since 2026-11-10. VERIFIED on the record level:
  `results/kg_hardening_eval/` abstention composition noted "structured source empty" on MH01/MH04/MH05, consistent with `executed=True` + no rows.
* The E14a golden prompts remain valid for 21 of 22 questions; Q04 is a parser change, not a retrieval change.

## What Person B must confirm

1. **Status contract of `customer_scoped_filter`.** The result dict carries `executed` (bool) and, only on the mapping path, `route="msisdn_mapping"`
   (also on each row's `metadata.route`); on the direct path there is no `route` key, and on the not-executable path there is `note` but no `route`.
   Is this the contract to rely on, and will it stay? I will then make my guard read `executed` / `route` / `note` from the result instead of
   catching an exception that no longer happens.
2. **Unknown customer = executed?** `customer_scoped_filter` returns `executed=True, note="unknown customer; nothing to scope to"` for a customer id
   that is not in `customer_master`. My guard and my tests say `executed=False` ("customer_master has no row for this customer"). Which do you
   want? If `True` stays, the only way to tell "unknown customer" from "known customer, no rows" is the `note` string; I would prefer an explicit
   key (for example `reason`/`route="unknown_customer"`) rather than parsing text.
3. **Note wording.** Your notes ("table has no customer key; cannot scope to a customer", "unknown customer; nothing to scope to") are what the user
   would see through my answer text. Can I treat them as stable, or should I keep my own wording and only use your `executed` flag?
4. **Q04.** Confirm that `exact_filter_unresolved` for "Why is my latest postpaid bill higher..." is the intended outcome of the word-boundary
   parser (`2f365ea`, `478256f`), i.e. that no filter should be inferred, so that I can regenerate the golden fixture for Q04 only and label the
   change "parser".
5. **`route` on the direct path.** The retriever sets no `route` key when the table has `customer_id`. If I default it to `"direct"` on my side, is
   that consistent with your meaning?
