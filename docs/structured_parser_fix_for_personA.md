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

---

# Part 2 of the fix: keyword strength, and customer scoping for msisdn-keyed tables

Branch: `person-b/parser-tiers-msisdn` (from `person-b/parser-wordboundary`). Not merged to main.

## A. Keyword-strength weights in the table detector (POST-HOC)

**Post-hoc label.** This tuning was designed AFTER Person A reported four questions that tie 1-1 under the word-boundary parser and
get no table. It is fitted to exactly those four (RB_S06, RB_B05, RB_B06, RB_S08); the old behaviour only passed them by dict-order luck.
The only unfitted evidence is the 22-item held-out file below, which was committed before the change and not edited afterwards.

**What changed (`structured/query_parser.py`).** Each distinct keyword hit adds `KEYWORD_WEIGHT[kw]` to its table's score:
weight **1** for `plan, account, profile, paid, site, port, order, offer, device, store`; **0.5** for bare `call`; weight **2** for every
other keyword. New keywords, weight 2: `call history, call record, call detail, call log` -> `cdr`. Exact table names still score 100.
A tie at the top score between different tables still returns `table None, error "ambiguous: t1,t2"`. The boundary-matching rule is unchanged.
The weights were set once, as specified, and not adjusted afterwards.

| Person A's question | Gold | Before (word-boundary parser) | After |
|---|---|---|---|
| RB_S06 "Is my latest bill paid or still pending?" | invoices | None (bill 1 vs paid 1) | invoices (bill 2 vs paid 1) |
| RB_B05 "My plan ran out ... can I still get incoming calls ...?" | subscriptions | None (plan 1 vs call 1) | subscriptions (plan 1 vs call 0.5) |
| RB_B06 "My latest postpaid bill looks higher than my plan rental ..." | invoices | None (bill 1 vs plan 1) | invoices (bill 2 vs plan 1) |
| RB_S08 "Are there any open complaints on my account?" | tickets | None (complaint 1 vs account 1) | tickets (complaint 2 vs account 1) |

**Held-out result** (`structured/tests/parser_heldout.json`, 22 items, `accept_abstain` marks items where "no table" is acceptable;
wrong = a wrong table, or an abstain where abstaining is not accepted):

| | correct | acceptable abstain | wrong |
|---|---|---|---|
| BEFORE (word-boundary parser) | 13 | 4 | **5** (all abstains: invoice/paid, plan/call, bill/plan, call-me/invoice, postpaid-bill/paid) |
| AFTER (weights) | 18 | 4 | **0** |

**Regression:** `benchmark.json` parsing 15/15 and end-to-end 15/15 (unchanged). Structured tests: 40 -> 45 (the held-out test, four reported-question
tests added). **One existing test was edited:** `test_two_tables_in_one_question_is_ambiguous_not_first_match` used "Show the plan and invoice for
customer 1001". With weights, `plan` (1) loses to `invoice` (2), so that pair is intentionally no longer a tie and now resolves to invoices.
The test's intent (a real tie must abstain) is preserved by changing the input to two strong keywords: "Show the invoice and ticket for customer 1001"
-> `ambiguous: invoices,tickets`.

**Behaviour to expect.** A weak keyword now loses to a strong one in another table even when a human might disagree
("Show the plan for my invoice" -> invoices). Two strong keywords of different tables still abstain.

## B. Customer scoping for msisdn-keyed and key-less tables (`structured/retriever.py`, not the parser)

**Problem.** `search()` and `exact_filter()` filtered every table with `customer_id`. Three tables (`cdr`, `recharge_transactions`,
`sim_inventory`) are keyed by `msisdn` and have no `customer_id` column, so "Show recharge transactions for customer 1056" crashed with
`OperationalError: no such column: customer_id`; ten more tables (offers, plan_master, network_sites, ...) have no customer key at all.

**What changed.** New `StructuredRetriever.customer_scoped_filter(table, customer_id)`; `exact_filter(..., "customer_id", ...)` and therefore
`search()` go through it:

| Table has | Behaviour |
|---|---|
| `customer_id` | unchanged: filter on customer_id |
| no `customer_id`, has `msisdn` | read the customer's own msisdn from `customer_master` (parameterised); exactly one row -> filter the table on msisdn, `metadata["route"] = "msisdn_mapping"` (and `route` on the result); unknown customer -> empty result with a note |
| neither (offers, plan_master, network_sites, ...) | empty result, note `table has no customer key; cannot scope to a customer`, `executed=False` |

Columns are read with `SELECT name FROM pragma_table_info(?)` (cached) after the table name is validated against the `schema.py` allowlist;
an unknown table is never queried. It never raises "no such column", never returns unscoped rows, never falls back to an unfiltered query.

| Call | Before | After |
|---|---|---|
| recharge_transactions / cdr / sim_inventory for customer 1056 | `OperationalError: no such column: customer_id` | only rows whose msisdn is customer 1056's |
| offers / plan_master / network_sites for a customer | `OperationalError` | empty, `executed=False`, note |
| unknown customer on an msisdn table | error | empty, note |
| `1001' OR '1'='1` as customer id | (not reached: error) | empty on every table tested |

Tests (`structured/tests/test_customer_scoping.py`, 11): 1056 recharges only that msisdn; cdr and sim_inventory likewise; customer_id tables unchanged;
key-less tables empty with the note; unknown customer; unknown table never queried; injection strings; `exact_filter` routed through scoping;
no "no such column" for any of the registered tables; **200 sampled customers x 6 tables, 3,373 rows, 0 foreign rows** (owner checked via a
msisdn -> customer_master join).

**Person A's `integration/structured_guard.py`** (not present in this repository, so I could not read it): once scoping lives in the retriever, a
guard that checks a table has a customer key before filtering becomes redundant. It is harmless to keep: it can only turn a call into an
empty result earlier, which is what the retriever does anyway.

**Caution - where the customer id comes from.** `customer_scoped_filter` trusts the id it is given. That id must come from the **signed-in session**,
never from question text: `parse_query` still extracts "customer 1001" from the words of the question, and a user can type any number. In the
hybrid layer the session id is passed separately (`run_hybrid_query(question, customer_id)`); a service that calls `StructuredRetriever.search(question)`
directly with user text will let a user ask about another customer. If you need `search()` to be safe by itself, pass the session customer id explicitly
and ignore the parsed one - I did not change that interface.

## Results for the whole branch

Structured tests 56 passed; `benchmark.json` 15/15 parsing and 15/15 end-to-end.
