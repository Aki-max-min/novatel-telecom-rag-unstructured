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
