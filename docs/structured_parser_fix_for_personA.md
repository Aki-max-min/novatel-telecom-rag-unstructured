# structured/query_parser.py - word-boundary and first-match fix (for Person A's Claude)

Branch: `person-b/parser-wordboundary` (from main at `f2249a6`). Not merged to main.
Only `structured/query_parser.py` and `structured/tests/test_queries.py` changed in `structured/`.

## Root cause (line numbers are from main before the fix)

- `structured/query_parser.py:111-124` `extract_status_value_for_table()`: `if status.lower() in q_lower` is a bare substring test, and
  values were tried in list order.
- `structured/query_parser.py:127-133` `detect_table()`: `if keyword in q_lower: return table` is a bare substring test **and** returns the
  FIRST hit in dict order, so a question that mentions two tables silently went to whichever keyword came first in `KEYWORD_TABLE_MAP`.

## False positives reproduced on main (before) and after the fix

| Question | Before | After |
|---|---|---|
| "What is important here?" | table = porting_requests ("port") | table None |
| "Show the report" | porting_requests | None |
| "Who gives support?" | porting_requests | None |
| "List postpaid customers" / "prepaid" | payment_transactions ("paid"); status "Paid" on invoices | None; status None |
| "Show inactive sim_inventory" | status **Active** ("active" inside "inactive") | status **Inactive** |
| "Show incomplete kyc_records" | status Complete | status None |
| "Show unresolved fraud_cases" | status Resolved | status None |
| "Give me an explanation" | subscriptions ("plan") | None |
| "Visit the website" | network_sites ("site") | None |
| "See the bottom of the page" | ott_subscriptions ("ott") | None |
| "Show the plan and invoice for customer 1001" | subscriptions (first match wins) | table None, error `ambiguous: invoices,subscriptions` |
| "Show esim_profiles for the customer profile" | customer_master ("profile") | esim_profiles |

(`similar sim cards` still resolves to sim_inventory: "sim cards" legitimately contains the word "sim". "similar" alone no longer does.)

## The new matching rule

A keyword matches only when it is not glued to a letter or digit on either side, and may carry an inflection:

```
(?<![a-z0-9])kw(?:s|es|ed|ing)?(?![a-z0-9])
```

Multi-word keywords match with flexible whitespace. Status values use the same boundary rule with **no** suffixes, longer values tried first.

**Why plain `\bkw\b` is wrong:** `_` is a regex word character, so in `recharge_transactions` there is no `\b` between `recharge` and `_`.
A plain `\b` breaks 8 of the 15 benchmark questions that name the table directly (recharge_transactions, payment_transactions,
sim_inventory, kyc_records, porting_requests, fraud_cases, escalation_cases, fiber_inventory). The lookarounds treat `_` as a separator.

**Scoring.** (1) An exact table name in the question (same boundary rule, no suffixes) scores 100 and wins over any keyword, so
`esim_profiles` no longer goes to customer_master via "profile". (2) Otherwise score = number of DISTINCT keyword hits per table
(not keyword length). (3) The highest score wins.

**Tie policy.** A tie between different tables is never guessed: `parse_query` returns `table None, method None, error "ambiguous: t1,t2"`
(tables sorted alphabetically). Downstream that yields an empty result, not a wrong table. Callers that want to ask the user to
disambiguate can read the table names from the error string. New helper functions: `score_tables()`, `detect_table_with_error()`;
`detect_table()` keeps its signature and returns None for no match or an ambiguous match.

## Tests added (structured/tests/test_queries.py, class `TestWordBoundaryRegression`, 11 tests)

port-inside-words, sim-inside-words, postpaid/prepaid not Paid, inactive -> Inactive, incomplete not Complete, unresolved not Resolved,
explanation/website/bottom match nothing, two-table question is ambiguous (not first match), the 8 underscore table names still resolve,
exact table name beats keywords, inflections still match (billing / billed / invoices / plans).
They were committed first (commit `202e4ba`): 9 failed, 2 passed (the two guard tests for unchanged behaviour).

## Regression results

| | Before | After |
|---|---|---|
| `structured/benchmark.json` parsing (evaluator.py) | 15/15 | 15/15 |
| End-to-end retrieval (evaluator.py) | 15/15 | 15/15 |
| structured unit tests | 29 passed | 40 passed (29 existing, unchanged, + 11 new) |
| full suite (hybrid + structured + integration, rag-api env) | 230 passed, 1 skipped | 241 passed, 1 skipped |

Unchanged and still covered by the existing tests: table-specific status casing ("pending" -> PENDING vs Pending), `invoices.payment_status`,
`esim_profiles.activation_status`, ICCID kept as string, and an unresolved filter still returns `exact_filter_unresolved` with an empty results list.
Running `evaluator.py` rewrites `structured/structured_retrieval_evaluation.json`; that file was restored and is not part of this change.

## Re-running your 22-query Base-vs-RAG benchmark

That benchmark is not in this repository, so I could not run it. To re-run it: check out this branch, run your harness unchanged, and
diff per-question table/filter decisions against your last results. Expect differences only for (a) questions whose old answer came from
a substring false positive (above), and (b) questions that mention two tables, which now return `ambiguous` with no results instead of a
first-match guess. Please send me any question whose result changes in a way that is not one of those two.

## Known limitations

- "in progress" (two words) does not map to the status value `InProgress`; "inprogress" / "in_progress" do not either. Not changed.
- Tie handling is conservative: a question with one keyword for each of two tables is rejected, even if a human would pick one.
- Keywords themselves are unchanged; some are still broad ("order", "call", "site", "offer").
