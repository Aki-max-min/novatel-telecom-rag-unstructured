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
