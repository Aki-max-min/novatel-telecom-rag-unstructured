# E13 link decoupling - results

Run exactly as pre-declared in `docs/E13_link_decoupling_rule.md`. Change under test: resolved RELATED_TO neighbours of the top-3 vector documents (cap 2) form their own fusion list with weight `w_link`, independent of the gate graph weight; the concept list is off, as in the current default. Baseline = graph off, links off. Dev sets only (main 29, mini 9, validation 14); Person A's 42 questions were not used. Reproduce: `python hybrid/evaluate_link_decoupling.py` (rag-api environment).

## Baseline

| set | R@1 | R@3 | R@5 | MRR@5 |
|---|---|---|---|---|
| main29 | 0.9310 | 1.0000 | 1.0000 | 0.9540 |
| mini9 | 0.4444 | 0.7778 | 0.7778 | 0.5926 |
| validation14 | 0.8571 | 0.9286 | 0.9286 | 0.8810 |
| pooled | 0.8269 | 0.9423 | 0.9423 | 0.8718 |

## Cells

| w_link | pooled W/L/net | main29 W/L | mini9 W/L | val14 W/L | questions where links were added (main/mini/val) | pooled R@1 | R@3 | MRR@5 (secondary) | incident pairs in final top 5 |
|---|---|---|---|---|---|---|---|---|---|
| 0.15 | 0/0/+0 | 0/0 | 0/0 | 0/0 | 17/5/10 | 0.8269 | 0.9423 | 0.8756 | 3/5 (off: 3/5) |
| 0.3 | 0/0/+0 | 0/0 | 0/0 | 0/0 | 17/5/10 | 0.8269 | 0.9423 | 0.8756 | 3/5 (off: 3/5) |
| 0.5 | 0/0/+0 | 0/0 | 0/0 | 0/0 | 17/5/10 | 0.8269 | 0.9423 | 0.8756 | 3/5 (off: 3/5) |

## Selection and verdict by the pre-declared rule

Selected (highest pooled net; ties: smaller w_link): **w_link = 0.15**.

- pooled losses <= 1: **True**
- no dev set net < -1: **True**
- incident check, links-on gets at least one more pair into the final top 5 than links-off: **False** (on 3/5 vs off 3/5)

**Verdict: FAIL.** Links stay OFF by default (`LINKS_ENABLED = False`); negative result.

Five incident pairs is a mechanism check, not generalisation evidence.

## Per-question wins and losses of the selected cell

(none: the selected cell changed no question's top-3 outcome)

## Incident mechanism check, per question

| question | links off | on w=0.15 | on w=0.3 | on w=0.5 |
|---|---|---|---|---|
| IL1 | pair NOT in top 5 | pair NOT in top 5 | pair NOT in top 5 | pair NOT in top 5 |
| IL2 | pair in top 5 | pair in top 5 | pair in top 5 | pair in top 5 |
| IL3 | pair in top 5 | pair in top 5 | pair in top 5 | pair in top 5 |
| IL4 | pair NOT in top 5 | pair NOT in top 5 | pair NOT in top 5 | pair NOT in top 5 |
| IL5 | pair in top 5 | pair in top 5 | pair in top 5 | pair in top 5 |

## Trace of IL4 with links on (w_link = 0.15)

Question: What was behind the period when nobody could sign in to the self-care app, and what was changed afterwards?

- gate graph weight: 0.0 (the concept list stays off; the link list does not depend on it)
- vector top-10: ['KB_C13_selfcare_login_issues', 'REL_2026_05', 'MAN_APP_001', 'RCA_INC_2026_0184', 'KB_C22_new_activation_delay', 'FAQ_C13_026', 'KB_C07_roaming_activation', 'KB_C05_sim_swap_troubleshooting', 'KB_C08_outage_status_check', 'SOP_C13_APP_ACCESS_ISSUES']
- link list: ['FAQ_C13_025']
- fusion order: ['KB_C13_selfcare_login_issues', 'REL_2026_05', 'MAN_APP_001', 'RCA_INC_2026_0184', 'KB_C22_new_activation_delay', 'FAQ_C13_026', 'KB_C07_roaming_activation', 'KB_C05_sim_swap_troubleshooting', 'KB_C08_outage_status_check', 'SOP_C13_APP_ACCESS_ISSUES', 'FAQ_C13_025']
- fusion sources of the pair: {'RCA_INC_2026_0184': ['vector']}
- final top 5: ['KB_C13_selfcare_login_issues', 'REL_2026_05', 'FAQ_C13_026', 'RCA_INC_2026_0184', 'MAN_APP_001']
- pair documents (fusion rank / rerank-only rank / final rank): {'INC_C13_INC_2026_0184': None, 'RCA_INC_2026_0184': {'rank_fusion': 4, 'rank_rerank': 6, 'final_rank': 4}}

IL1 is a reranker miss (the CrossEncoder ranked the partner 9 of 9 in the pool); the reranker is not changed here.

## Reading the result (added by hand after the run)

- **Verdict FAIL, stated plainly: a negative result.** The two dev-set conditions hold trivially (0 wins, 0 losses in every cell, so pooled losses <= 1 and no set below -1),
  but the third condition - at least one more incident pair in the final top 5 - fails: links-on 3/5, links-off 3/5 for every `w_link`. Links stay OFF by default.
- **The three cells are indistinguishable.** Links were added for 17 of 29, 5 of 9 and 10 of 14 dev questions, yet no top-3 outcome changed and the final top-5
  composition did not depend on `w_link` in 0.15-0.50; the cells tie and the smaller `w_link` (0.15) is reported as selected by the tie-break.
- **Why IL4 still fails - a consequence of a pre-declared parameter, not a bug.** The question's vector list is `KB_C13_selfcare_login_issues, REL_2026_05,
  MAN_APP_001, RCA_INC_2026_0184, ...`: the RCA document sits at vector rank **4**, and the rule fixed the link seeds at the **top 3** documents. So the RCA's
  link to its INC partner is never followed; the top-3 seeds link to `FAQ_C13_025`, which is what the link list contained. The rule was not changed after seeing this.
  Whether seeds = 4-5 would help is a question for a new pre-declared experiment, not something to read off this run.
- **IL1 is a reranker miss**, not a link problem: the partner was vector rank 2 and fusion rank 2, and the CrossEncoder ranked it 9 of 9 in the pool (blend rank 6).
  Recorded as such; the reranker is not changed.
- Five incident pairs is a mechanism check, not generalisation evidence; the dev sets cannot resolve differences smaller than one question.
