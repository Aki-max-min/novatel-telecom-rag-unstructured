# E13 Phase 8 - post-hoc fix log

**Read this first.** Every change below was made **after** seeing the first-run results of the frozen
route benchmark (`hybrid/benchmark/first_run_phase7.json`, committed at `bde1a4e`, untuned). The first-run
numbers remain the headline (route 21/24, structured fact recall 23/30, document hit@3 unstructured 8/8 and
both 4/6, leakage 0). The amended run is a separate, labelled `post_hoc: true` file. These fixes were
motivated by observed failures, so the amended numbers measure "does the general rule repair what we
saw", not generalisation.

The frozen files `route_benchmark.json` and `first_run_phase7.json` were not edited.

Rule applied to each fix: observed failure -> a **general** rule (not a patch for one question) -> a unit
test whose sentence appears in no benchmark file.

| # | Observed failure | General rule | Test |
|---|---|---|---|
| 1 | Verified root cause: `query_gate.py` mixed word-start matching (concept patterns) with whole-word matching (`_PERSONAL_FACT` ended in `\b`), so plural facts ("complaints", "tickets", "invoices", "payments", "bills", "plans", "orders", "recharges") were not personal facts: `Are my ticket still open?` -> personal, `Are my tickets still open?` -> not. First-run misses RB_S05 and RB_S08 trace to this ("complaints"). | One shared matcher, `hybrid/textmatch.py`: word-boundary at the start, optional inflection (s/es/ed/ing, silent-e and -y rules), flexible hyphen/space, explicit open stems (`expir*`), `inflect=False` for pronouns and grammar words. Used for every keyword list in `query_gate.py` and `router.py`. No term was deleted; regex-fragment terms were rewritten as plain terms (`port(?:ing|ability|ed)?` -> `port`, `porting`, `portability`; `fib(?:er|re)` -> `fiber`, `fibre`; `expire` kept and `expiry` added). | `test_textmatch.py`: generated from the lists, 630 keyword checks - singular, plural, -ed, -ing all match; prefix ("re"+kw) and non-inflection suffix (kw+"et") do not. Plus `test_phase8_fixes.py::test_plural_personal_facts`. |
| 2 | Phase 5 / first-run review: "promo" matched "promotional", giving DND-style questions an Offers & Promotions hint and graph weight 0.15. | "promo" is a whole term (promo/promotions). Unsolicited-communication questions (promotional/marketing/spam/unsolicited/telemarketing + sms/message/call/text) get concept_hint None and graph_weight 0.0, because that topic has no concept in the vocabulary (concept_bridge.py: no DND table). | `test_a_promotional_does_not_match_promo` (marketing calls, unsolicited text messages -> None; "promotional offers on recharge" -> Offers & Promotions). |
| 3 | Bare "number" made "How much will I be charged ... a number in another country" personal. | "number" only counts inside a possessive phrase: my number / my mobile|phone|sim number. | `test_b_bare_number_is_not_personal`. |
| 4 | First-run miss RB_B04: "which documents do I have to submit" was not a policy component. | Policy cue `(which\|what) <word> (do\|should\|must) (i\|we) [have\|need\|got\|want to] (submit\|provide\|bring\|carry\|need)`. **Note:** this extends the literal spec by allowing "have to / need to" before the verb, because the observed failure used "do I have to submit". "subscribed/subscribe" added to the subscription intent. | `test_c_policy_cue_generalisation`, `test_c_subscribe_is_a_subscription_intent`. |
| 5 | Phase 5 review of concept hints: handset+5G -> Network Coverage; enterprise plan -> Plan Catalogue. | Combination rules: handset/phone/device + 5g/volte -> Device Compatibility; enterprise/business/corporate + plan/connectivity/sim -> Enterprise & Business Services. A target concept missing from the vocabulary is never forced (`MISSING_CONCEPT_TARGETS`). **Both targets exist in the vocabulary; nothing was missing.** | `test_d_concept_hints`. |
| 6 | Safeguard (not an observed benchmark failure): personal-looking requests with no recognisable detail silently fell through to documents. | `unrecognised_personal_request` flag on `RoutePlan`, copied to `blocked` and `trace` by `run_hybrid_query`; outcome stays `answer`. **Definition used:** possessive phrasing (my/mine), no supported structured intent, no policy cue, route unstructured. Plain "I" is not enough, otherwise every how-to question would be flagged. | `test_e_unrecognised_personal_request_flag`, `TestPipelineFlags`. |
| 7 | Safeguard: "my mother's last recharge" would have been answered from the asker's own account. | Third-party possessive (my + kin, optional 's) with a personal fact or structured intent and no how-to cue -> `refuse_other_customer`, reason `third_party_reference`, zero facts and zero documents. A how-to ("How can I recharge for my mother?") goes to documents only. | `test_f_*`. |

## Existing tests that had to change

Two earlier tests hard-coded the Phase 2 gate weight for the DND sentence (0.15, the false-positive hint).
Fix 2 deliberately changes it to 0.0, which also removes graph-only `doc_D` from that fusion output:

- `test_fusion.py::test_fuse_and_select_three_questions` - DND expectation 0.15 -> 0.0, order `[A, C, B, D]` -> `[A, B, C]`.
- `test_rerank.py::test_pipeline_three_questions` - DND result length 4 -> 3.

No other existing test needed editing; the doc_A..doc_D fusion arithmetic tests are unchanged.

## Side effect to expect

The gate feeds the fusion weight, so these fixes can change graph weights and therefore document rankings
on the Phase 5 benchmarks. Phase 8c re-runs both and reports the differences against the Phase 5 rows.

---

## Amended run on the frozen benchmark (Phase 8c, post-hoc) - outcome

`hybrid/benchmark/amended_run_phase8.json` (`"post_hoc": true`) vs the untuned first run `first_run_phase7.json` (`bde1a4e`, unchanged).

| Metric | First run (untuned) | Amended (post-hoc) |
|---|---|---|
| Route accuracy | 21/24 | 23/24 |
| Outcome accuracy | 24/24 | 23/24 |
| Structured fact recall | 23/30 | 30/30 |
| Leakage | 0 | 0 |
| Document hit@3 / hit@5, unstructured items | 8/8 / 8/8 | 7/8 / 7/8 |
| Document hit@3 / hit@5, both items | 4/6 / 4/6 | 5/6 / 6/6 |
| Safety (needs_identity / refuse_other_customer) | pass / pass | pass / pass |

Fixed by the Phase 8a rules: RB_S05 and RB_S08 (plural "complaints", 7 missing facts), RB_B04 (policy cue; its documents now run).
Document gains in the both items also reflect the adopted rerank variant (V1).

**A regression introduced by the fixes (found by this run, NOT yet fixed):** RB_U01 ("... can both be applied when I top up once?")
was correct in the first run and is wrong now: the route became `structured` / `needs_identity` and no documents ran, so the unstructured
items drop from 8/8 to 7/8 and outcome accuracy from 24/24 to 23/24. Cause: the shared matcher makes the term "top-up" match "top up"
(flexible hyphen/space, as specified), so the *verb* "top up" is read as the recharge account fact ("I ... top up") and the question is treated as personal.
This is a false positive created by fix 1, i.e. an example of a post-hoc change generalising badly; it is reported, not patched,
because a further change made now would be tuned on the same frozen set. Candidate fixes for a later phase: allow the space/hyphen
variants only for the noun use (e.g. require an article/possessive before it) or drop "top up" from the personal-fact list.

Remaining miss besides that: RB_B01 hit@3 (expected FAQ_C17_034 / KB_C17_kyc_reverification; FAQ_C17_034 is now at rank 5).

### Main-29 / mini-9 regression vs the Phase 5 rows (`evaluation_results_post_phase8.json`)

Vector-only, blanket-graph and the no-rerank diagnostic arm are **unchanged** on both sets. Only the E13 hybrid row moves (gate weights
changed on 2 main questions: the porting question 0.5 -> 0.15 because bare "number" is no longer personal, and the DND-promotional
question 0.15 -> 0.0; the rerank variant changed from V0 to V1):

| E13 hybrid | Phase 5 (V0) | Now (V1) |
|---|---|---|
| Main R@1 / R@3 / R@5 / MRR@5 | 0.9310 / 1.0000 / 1.0000 / 0.9598 | 0.8276 / 1.0000 / 1.0000 / 0.9080 |
| Mini R@1 / R@3 / R@5 / MRR@5 | 0.2222 / 0.6667 / 0.8889 / 0.4759 | 0.5556 / 0.7778 / 0.8889 / 0.6574 |

So the adopted variant trades main-benchmark top-1 accuracy (0.9310 -> 0.8276) for the graph-dependent gains (R@1 0.2222 -> 0.5556).
The main-benchmark R@1 now sits above vector-only (0.7586) but below Person A's existing rerank-only result (0.9310).
