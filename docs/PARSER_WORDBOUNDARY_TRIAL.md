# Trial of `origin/person-b/parser-wordboundary` (no LLM, local branch only)

Run by Person A on 2026-10-31. **Nothing was merged into `integrate/kg-ontology-router-ui`; the trial lives on the local branch
`trial/parser-wordboundary` (HEAD 394cd99) and was not pushed.** No model or LLM was used: only Person B's rule-based parser and
the SQLite retriever.

## Merge
* `git switch -c trial/parser-wordboundary` from `a2faccf`, then `git merge --no-ff origin/person-b/parser-wordboundary`.
* **Conflicts: none** (clean `ort` merge). Files brought in: `structured/query_parser.py` (+72/-11), `structured/tests/test_queries.py` (+61), `docs/structured_parser_fix_for_personA.md` (+86).
* Parser version in use: before = `structured/query_parser.py` blob `4ce2f6cc2e` (integration branch); after = blob `34378a176c` (trial).

## Method
`integration/eval/parser_trial.py` (committed on the integration branch, identical on both sides) runs 43 existing questions and records the parse (table, method, filter, error) and the rows the retriever returns:
15 questions of Person B's `structured/benchmark.json`, the 14 E14a document questions (database ones are the same questions as the benchmark), and 14 answerable structured / "both" items of Person B's route benchmark
(session customer made explicit with the prefix "For customer <id>: "). Definitions of regression / improvement are in the module docstring. Raw runs: `data/experiments/parser_trial/{before_integrate,after_trial,compare_*}.json`.

## Result
| | before | after |
|---|---|---|
| structured benchmark: questions with a gold table whose parse (table + filter) is correct | 14 of 14 | 14 of 14 |
| (S15 is the negative control, gold has no table; it is not counted above) | | |
| E14a document questions that still return structured rows (false positives) | 3 of 14 (Q04, Q17, Q20) | 2 of 14 (Q17, Q20) |
| questions whose outcome changed | | 5 of 43 |

### Every difference
| Question | Before | After | Verdict |
|---|---|---|---|
| **Q04** (E14a document): "Why is my latest postpaid bill higher than the monthly rental I expected to pay?" | `invoices`, filter `payment_status = Paid` ("postpaid" contains "paid"), 10 rows | filter unresolved, 0 rows | **improvement**: a false 10-row structured hit is removed |
| **RB_S06**: "For customer 1829: Is my latest bill paid or still pending?" | `invoices` by customer, 6 rows (gold table) | `ambiguous: invoices,payment_transactions`, 0 rows | **regression**: gold evidence lost |
| **RB_B05**: "For customer 1056: My plan ran out ... incoming calls ..." | `subscriptions` by customer, 1 row (gold table) | `ambiguous: cdr,subscriptions`, 0 rows | **regression**: gold evidence lost |
| RB_S08: "For customer 1015: Are there any open complaints ...?" | `customer_master` (not a gold table), 1 row | `ambiguous: customer_master,tickets`, 0 rows | changed, gold evidence unchanged (a wrong table became no table) |
| RB_B06: "For customer 1003: My latest postpaid bill looks higher ..." | `subscriptions` (not a gold table), 1 row | `ambiguous: invoices,subscriptions`, 0 rows | changed, gold evidence unchanged |

All other questions are identical, including every database question of the structured benchmark and the 8 database questions of E14a.

### What this shows
* The word-boundary fix does what it says (the "postpaid" -> "Paid" false positive disappears).
* The new "ambiguous tie returns no table" rule removes structured evidence from customer questions that mention two tables. For 2 of the 14 route-benchmark items the old first-match had happened to pick the right table, so the net effect on those two is a loss.
  For 2 others the old pick was wrong and the new result is an honest "no table". This is the behaviour Person B documents ("a tie ... is never guessed").
* Q17 and Q20 (document questions) still return 10 structured rows each, so the trial does not remove all parser false positives.
* **This is a retrieval-side comparison on 43 questions with stated definitions. It does not measure answer quality**; effects on answers were not run.

## Tests on the trial branch
| Suite | Result |
|---|---|
| `structured/tests` | 40 passed, 88 subtests passed (29 existing + 11 new regression tests) |
| `hybrid/tests` | 181 passed, 1 skipped (same as on the integration branch) |
| Person A: `query_router/tests` + `integration/tests` | 157 passed, **1 failed**: `test_default_prompts_identical_to_head` |

The one failure is the golden-prompt regression test doing its job: with the new parser, the assembled E14a prompt for **Q04** changes (its 3 false invoice-row blocks disappear). It is the only E14a prompt that changes. If the parser branch is adopted, the golden
file would need regenerating (and the E14a-comparable baselines re-labelled as "old parser").

## Merging (not run)
To adopt the parser fix on the integration branch (equivalent to what the trial did, without the trial branch's merge commit):

    git switch integrate/kg-ontology-router-ui && git merge --no-ff origin/person-b/parser-wordboundary

Decision points for you and Person B: the two regressions above (RB_S06, RB_B05), the golden-prompt file for Q04, and whether arms of the final measurement should run on the old or the new parser (the plan so far uses the old one).
