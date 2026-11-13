# E13 KG fixes 4 - precision pass on the vocabulary overlay: rule (pre-declared) and results

Branch `person-b/kg-fixes4`, started from the pushed head of `person-b/kg-fixes3` (`bd8f673`). KG fixes 3 raised the documents with a content concept from 129 to 144 but its report showed
matches in the wrong sense (mainly `deactivate`/`deactivated`, and `Airplane Mode`). This pass narrows phrases for **documented wrong senses only**. **This rule is committed before the per-concept table is re-run;
results are appended below and the rule is not edited.** Same hard limits as before: nothing under `integration/`, `data/`, `ontology/` or the benchmarks; no LLM, no embeddings, no new retrieval layer; dev sets only.

## Rule

1. **A phrase may be narrowed or removed ONLY for a documented wrong sense**, judged by reading the matched snippet (with its surrounding sentence and the document title), **never from retrieval metrics** and never to
   improve a count. Every change is listed with the document, the snippet and the reason (`docs/E13_kg_fixes4_judgements.csv`).
2. **Judgement of every match** (a (concept, phrase, document) triple, for all ten kept concepts in the KG fixes 3 state; the three dropped concepts have no effect and are not judged):
   *correct sense* = the phrase is used with the concept's meaning; *wrong sense* = the phrase is used with another meaning (e.g. deactivating a VAS or an old SIM under "Account Closure & Deactivation");
   *unsure* = a reader could reasonably go either way. **Unsure matches are marked and left unchanged.** The judgements are mine, made from the snippets; they are listed so they can be checked and overruled.
3. **Level of the change:** (i) a phrase whose matches are in a wrong sense is replaced by a more specific phrase or removed; (ii) a wrong-sense match that no narrower phrase can remove, in a document that also has correct-sense
   matches for that concept, is removed by a documented `exclusions` pair; a phrase is never narrowed merely because it matches few documents. Removed phrases stay in the overlay file (key `narrowed_phrases`, with reason and documents); no rule is deleted.
4. **Requested changes:** (1) in *Account Closure & Deactivation* the bare phrases `deactivate` and `deactivated` are replaced by specific phrases that occur in the correct-sense documents:
   `permanently deactivate` (FAQ_C21_041, "How do I permanently deactivate/close my postpaid connection?"), `deactivated for non-payment` (FAQ_C21_042 and SOP_C21_ACCOUNT_CLOSURE), `Deactivated Connection`
   (KB_C21_account_closure, "Closing or Reactivating a Deactivated Connection"). These three are fixed here; a replacement that turns out to match a wrong-sense document is dropped and reported, not adjusted.
   (2) `Airplane Mode` is removed from *Connectivity Troubleshooting* (it matches an app-login SOP). (3) Every other match outside the evidence file is judged as above and only the wrong-sense ones are narrowed.
5. **Acceptance (same rule as KG fixes 3):** no concept over 14 of the 148 documents; a NEW concept links at least 2 documents (otherwise it is dropped by the rule, whatever the reason it fell short); an EXISTING concept grows by at most 2 documents;
   100% of the new edges have their evidence phrase in the body (proxy, not validation); dev sets: top 5 of all 52 questions identical to the KG fixes 3 graph, 0 losses at R@1, R@3, R@5, incident pairs 3/5 vs 3/5; two graph builds byte-identical;
   tests green, structured benchmark 15/15, frozen files identical.
6. **Coverage is not a goal here.** If narrowing uncovers a document that KG fixes 3 covered (including because a NEW concept falls under 2 documents and is dropped by rule 5), that is reported and the narrower rule is kept.
7. **Reported:** documents with a concept before and after, the uncovered documents, each concept's document count, and the number of wrong-sense matches before and after, counted from the judgements table.

## What is NOT shown (stated up front)

The dev sets are the sets everything was developed on; "identical top 5" is not generalisation evidence. The wrong-sense judgements are one reader's (mine); extraction quality remains unvalidated until the human gold sheet
(`docs/extraction_gold_sheet.csv`) is filled. Person A's 42 questions remain the unbiased test and are not used.

---

# Results (appended 2026-11-14; the rule above was committed first, in `c0defdd`, and is unchanged)

Commands: `python -m knowledge_graph.evaluate_vocabulary_extension --apply`, `python -m knowledge_graph.judge_overlay_matches` (writes `docs/E13_kg_fixes4_judgements.csv`, all 80 matches with snippets), and
`FX_GRAPH_A=<kg-fixes3 graph> FX_GRAPH_B=<now> python hybrid/evaluate_fixes.py fx3_overlay` for the dev sets.

## Wrong-sense matches before and after (counted from the judgements table; the judgements are mine, for you to check)

| | matches (concept, phrase, document) | correct sense | wrong sense | unsure | wrong-sense share |
|---|---|---|---|---|---|
| before (KG fixes 3 phrase set, ten kept concepts) | 80 | 72 | 7 | 1 | 7 of 80 |
| after (this pass) | 71 | 70 | 0 | 1 | 0 of 71 |

(Correction of an earlier remark of mine: I called the 80 matches "89"; that was the line count of my listing file, which includes ten concept header lines. The table has 80.)
Matches changed or newly created (the other 66 matches are unchanged and judged correct sense; the 80 plus the 4 new ones are all in the CSV):

| concept | phrase | document | judgement | before -> after | action | snippet |
|---|---|---|---|---|---|---|
| Device Compatibility | `VoLTE` | REL_2026_06 | unsure | yes -> yes | unchanged | Network Platform Release — VoLTE Band Expansion # Release Notes: Network Platform Release — VoLTE Band Expansion |
| Account Closure & Deactivation | `deactivate` | FAQ_C10_019 | wrong sense | yes -> no | phrase narrowed | ... (caller tunes, content packs, insurance add-ons, etc.) and deactivate any you did not authorise. Unauthorised VAS activation can also be reported via... |
| Account Closure & Deactivation | `deactivate` | FAQ_C21_041 | correct sense | yes -> no | phrase narrowed | How do I permanently deactivate/close my postpaid connection? Question: How do I permanently deactivate/close my postpaid |
| Account Closure & Deactivation | `deactivate` | SOP_C05_SIM_REPLACEMENT | wrong sense | yes -> no | phrase narrowed | ... account before proceeding. Issue new SIM with same number; deactivate old SIM as part of the same transaction. Instruct customer to restart device an... |
| Account Closure & Deactivation | `deactivate` | SOP_C10_VAS_DISPUTE | wrong sense | yes -> no | phrase narrowed | ... approve a full refund of charges for the disputed service. Deactivate the VAS immediately regardless of the consent outcome, if the customer requests... |
| Account Closure & Deactivation | `deactivate` | TRN_001 | wrong sense | yes -> no | phrase narrowed | ...t be verified, process a refund per SOP_C10_VAS_DISPUTE and deactivate the service. ## Assessment Checklist - [ ] Agent verified customer identity bef... |
| Account Closure & Deactivation | `deactivated` | EML_001 | wrong sense | yes -> no | phrase narrowed | ...₹149 to your account balance, effective today. We have also deactivated the service to prevent recurrence. Warm regards, NovaTel Billing Support ## Re... |
| Account Closure & Deactivation | `deactivated` | FAQ_C21_042 | correct sense | yes -> no | phrase narrowed | Can I reactivate a number that was deactivated for non-payment? Question: Can I reactivate a number that was deactivated for non-payment |
| Account Closure & Deactivation | `deactivated` | KB_C21_account_closure | correct sense | yes -> no | phrase narrowed | Closing or Reactivating a Deactivated Connection # Closing or Reactivating a Deactivated Connection --- ## Summary Th |
| Account Closure & Deactivation | `deactivated` | MAN_ESIM_001 | wrong sense | yes -> no | phrase narrowed | ...(typically within 10 minutes). ## Notes The physical SIM is deactivated automatically once the eSIM profile is confirmed active. ## Prerequisites - A ... |
| Account Closure & Deactivation | `deactivated` | SOP_C21_ACCOUNT_CLOSURE | correct sense | yes -> no | phrase narrowed | ...osure of active connections and reactivation of connections deactivated for non-payment. Scope Applies to all channels and customer segments unless a ... |
| Account Closure & Deactivation | `Deactivated Connection` | KB_C21_account_closure | correct sense | no -> yes | replacement phrase | Closing or Reactivating a Deactivated Connection # Closing or Reactivating a Deactivated Connection --- ## Summary This article |
| Account Closure & Deactivation | `deactivated for non-payment` | FAQ_C21_042 | correct sense | no -> yes | replacement phrase | Can I reactivate a number that was deactivated for non-payment? Question: Can I reactivate a number that was deactivated for non-payment? Answer: ### ... |
| Account Closure & Deactivation | `deactivated for non-payment` | SOP_C21_ACCOUNT_CLOSURE | correct sense | no -> yes | replacement phrase | ...osure of active connections and reactivation of connections deactivated for non-payment. Scope Applies to all channels and customer segments unless a ... |
| Account Closure & Deactivation | `permanently deactivate` | FAQ_C21_041 | correct sense | no -> yes | replacement phrase | How do I permanently deactivate/close my postpaid connection? Question: How do I permanently deactivate/close my postpaid |
| Connectivity Troubleshooting | `Airplane Mode` | FAQ_C29_057 | correct sense | yes -> no | phrase removed | ...ssue rather than a device fault. Restart the device, toggle Airplane Mode, and if unresolved, contact care with your number so the account can be re-p... |
| Connectivity Troubleshooting | `Airplane Mode` | SOP_C13_APP_ACCESS_ISSUES | wrong sense | yes -> no | phrase removed | ...dure Confirm SIM has active signal and the device is not on Airplane Mode. Attempt OTP resend after the mandatory 30-second cooldown. If OTP still fai... |
| Connectivity Troubleshooting | `Reset Network Settings` | FAQ_C29_058 | correct sense | yes -> no | concept dropped by rule (b) | ...roid/iOS devices, go to Settings > General/System > Reset > Reset Network Settings. This clears saved Wi-Fi/APN/Bluetooth configurations, so ensure yo... |

Notes on the table:
- The seven wrong-sense matches: six in Account Closure & Deactivation (deactivating a VAS in FAQ_C10_019, SOP_C10_VAS_DISPUTE and TRN_001; the old SIM in SOP_C05_SIM_REPLACEMENT; a service deactivated after a refund in EML_001; the physical SIM replaced by an eSIM in MAN_ESIM_001) and one in Connectivity Troubleshooting (the OTP precondition in SOP_C13_APP_ACCESS_ISSUES).
- The four correct-sense documents that the bare `deactivate`/`deactivated` used to reach (FAQ_C21_041, FAQ_C21_042, KB_C21_account_closure, SOP_C21_ACCOUNT_CLOSURE) are reached again by the three specific phrases; none of the three specific phrases matches a wrong-sense document (checked in the table).
- The only unsure match, `VoLTE` in REL_2026_06 (a network release note on VoLTE band expansion), is left unchanged as the rule says.
- Two correct-sense matches are lost as a side effect: `Airplane Mode` in FAQ_C29_057 (the phrase was removed as requested; no narrower phrase separates it from the app-login SOP) and `Reset Network Settings` in FAQ_C29_058 (its concept is dropped, see below).
  A per-document exclusion for SOP_C13_APP_ACCESS_ISSUES would have kept FAQ_C29_057 and the concept alive with 2 documents; it was not applied because the request was to remove the phrase. It is a one-line change if you prefer it.
- The three dropped concepts of KG fixes 3 (Billing & Invoices, Enterprise & Business Services, International Calling & ISD) have no effect and were not judged.

## Per-concept table after the pass (all 148 documents)

| concept | status | documents | newly covered | growth over existing group | evidence in body | decision |
|---|---|---|---|---|---|---|
| Device Compatibility | EXTEND | 4 | 2 | 1 | 4/4 | KEEP |
| Billing & Invoices | EXTEND | 7 | 0 | 5 | 7/7 | DROP: growth 5 > 2 (as in KG fixes 3) |
| Network Outages | EXTEND | 3 | 1 | 0 | 3/3 | KEEP |
| Security & Fraud | EXTEND | 6 | 1 | 0 | 6/6 | KEEP |
| SIM Card Services | EXTEND | 1 | 1 | 1 | 1/1 | KEEP |
| Enterprise & Business Services | EXTEND | 4 | 0 | 3 | 4/4 | DROP: growth 3 > 2 (as in KG fixes 3) |
| IoT & M2M Services | NEW | 3 | 3 | 3 | 3/3 | KEEP |
| Privacy & Data Protection | NEW | 3 | 2 | 3 | 3/3 | KEEP |
| International Calling & ISD | NEW | 1 | 0 | 1 | 1/1 | DROP: (b) one document (as in KG fixes 3) |
| Account Closure & Deactivation | NEW | **7** (was 13) | 3 | 7 | 7/7 | KEEP |
| Fair Usage Policy (FUP) | NEW | 7 | 1 | 7 | 7/7 | KEEP |
| Connectivity Troubleshooting | NEW | **1** (was 3) | 0 | 1 | 1/1 | **DROP: (b) a NEW concept must link at least 2 documents** (new in this pass) |
| Accessibility & Communication Preferences | NEW | 2 | 1 | 2 | 2/2 | KEEP |

No phrase is a hub; no kept concept is over 14 documents (largest 7). Account Closure & Deactivation now covers EML_005, FAQ_C19_038, FAQ_C21_041, FAQ_C21_042, KB_C21_account_closure, SOP_C21_ACCOUNT_CLOSURE, TRX_008.

## Coverage

- Documents with a content concept: **129 before the vocabulary overlay, 144 after KG fixes 3, 143 after this pass.** The one document lost against KG fixes 3 is `FAQ_C29_058`: it was covered only by Connectivity Troubleshooting, which falls under 2 documents once `Airplane Mode` is removed. Kept as the rule says (precision before coverage).
- **Uncovered (5):** FAQ_C11_021 (International Calling dropped: one document), FAQ_C11_022 (documented exclusion), FAQ_C23_045 (Enterprise dropped), FAQ_C29_058 (Connectivity Troubleshooting dropped, new), INC_C04_INC_2026_0163 (Billing dropped).
- `FAQ_C29_057` stays covered through SIM Card Services (`not provisioned`).

## Acceptance

- No concept over 14 documents; NEW concepts link at least 2 documents or are dropped; EXISTING growth at most 2 (or dropped); evidence 100% for every kept concept (proxy, not validation).
- Dev sets, graph of KG fixes 3 vs graph now: **top 5 identical for all 52 questions**, 0 losses and 0 gains at R@1, R@3 and R@5, pooled R@1 0.8269 / R@3 0.9423 / R@5 0.9615 / MRR@5 0.8756 in both arms, incident pairs 3/5 vs 3/5.
- Two graph builds are byte-identical (`graph.json`, `nodes.json`, `edges.json`, `content_extraction.json`). `graph.json`: 345 -> 344 nodes (5 overlay Concept nodes), 1739 -> 1730 edges (`MENTIONS_CONCEPT` 49 -> 40).
- Tests: see the gates in the hand-over message; the tests that pin counts were updated (concept nodes 23 + 6 -> 23 + 5, `MENTIONS_CONCEPT` 49 -> 40, `index.concepts()` 29 -> 28, real-corpus coverage 144 -> 143 and the uncovered list, the proposal-content test now expects the three added phrases).

## What is NOT shown

The dev sets are the sets everything was developed on, so "identical top 5" is not generalisation evidence. The wrong-sense judgements are one reader's (mine) from the snippets; the 66 unchanged correct-sense matches have not been reviewed by a second person.
Extraction quality remains unvalidated until the human gold sheet (`docs/extraction_gold_sheet.csv`) is filled; the evidence check is a proxy. Person A's 42 questions remain the unbiased test and were not used.
