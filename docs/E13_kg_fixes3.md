# E13 KG fixes 3 - applying the Gap 5 vocabulary proposal: rule (pre-declared) and results

Branch `person-b/kg-fixes3`, started from the head of `person-b/kg-fixes2` (`01581a0`). The proposal (`gap5_vocabulary_extension_proposal.json`, evidence in
`gap5_vocabulary_evidence.csv`) names trigger phrases for the 19 documents that still have no content concept. It is **proposed, pending ontology-owner approval**: it
lives in an overlay file, never in the shared `ontology/` folder. **This rule is committed before any measurement; results are appended below and the rule is not edited.**

Hard limits: nothing under `integration/`, no edit of `data/processed` documents or their `related_ids`, nothing in `ontology/`, no frozen benchmark file, no Person A branch;
no LLM, no embeddings. Dev sets only (main 29, mini 9, validation 14 = 52 questions, plus the 5 incident pairs); Person A's 42 questions are never used.

## What is built

- `knowledge_graph/vocabulary_extension.json` - the proposal plus `"status": "proposed, pending ontology-owner approval"`, an explicit `exclusions` list and, after step 4, the
  recorded `dropped` concepts and `dropped_phrases` (rules are never deleted: a dropped rule stays in the file with its reason). 6 `EXTEND existing` concepts' phrases (7 are `NEW`) are added to
  that concept's mention triggers through the overlay (existing extraction rules are not edited); the `NEW` concepts exist only in the overlay and become `Concept` nodes in
  `graph.json` with property `source="vocabulary_extension"` (the shared crosswalk vocabulary stays at 23 concepts).
- Matching: boundary-safe, case-insensitive (the extractor's own matcher), on the document BODY only: title + content without the metadata header lines, the `Topic:` footer and the
  `Related Information` / `Related Documents` / `References` sections. Every hit is a `MENTIONS_CONCEPT` edge with phrase, field and snippet. The overlay refuses (loader error) any
  phrase that is a generic template word (`outage`, `troubleshooting`, `bill`, ...; list in the overlay).
- Exclusions: `FAQ_C11_022 -> Network Coverage` and `FAQ_C09_017 -> Device Compatibility` (the two doubtful senses found in KG fixes 2) are removed by a documented `exclusions` entry
  that applies to any rule producing that (document, concept) pair; the name-family rules that produced them are not deleted.
- Retrieval: `MENTIONS_CONCEPT` is not a bridge of `graph_expand`; nothing here may move a ranking, and acceptance (e) checks that.

## Acceptance rule (all must hold; a concept that fails is dropped and reported, the rest are kept)

Definitions. *Matched documents* of a concept = documents with a `MENTIONS_CONCEPT` edge to it after exclusions, over ALL 148 documents. *Existing document group* of an existing concept =
documents of its categories and mapped services (the group used in KG fixes 2). *Growth* = matched documents that are not in that group. *Newly covered* = matched documents that had no
content concept in the state before this task (129 documents) and are not already claimed by an earlier concept in overlay order (informational). *Hub phrase* = a single phrase that matches more
than 14 documents.

- **Phrase hub rule (applied first, once, from corpus counts only):** a phrase that alone matches more than 14 of the 148 documents is dropped and reported; no phrase is changed or added afterwards.
- (a) no concept is matched by more than 14 of the 148 documents, and no EXISTING concept grows by more than 2 documents;
- (b) a NEW concept must link at least 2 documents, otherwise it is dropped (a one-document concept creates no link);
- (c) 100% of the new edges have their evidence phrase in the body (automatic check; **a precision proxy, not validation** - it is the matcher's own rule and cannot detect a wrong sense);
- (d) overall: the number of documents with a content concept rises from 129; the new number and the documents still uncovered are listed. If it does not rise, the overlay is not activated;
- (e) dev sets: the top 5 of all 52 questions identical before and after, 0 losses at R@1, R@3 and R@5, incident pairs 3/5 vs 3/5, and two graph builds byte-identical. If (e) fails, the overlay is not activated.
Per-concept table printed by `python -m knowledge_graph.evaluate_vocabulary_extension`: concept, documents matched, newly covered documents, growth over the existing group.
Phrases that match in documents other than those in the evidence file are reported with their snippet (possible wrong sense). **No phrase is tuned after seeing dev-set results.**

## What is NOT shown (stated up front)

The dev sets are the sets everything was developed on, so a verdict is not generalisation evidence and differences below one question cannot be resolved. Extraction quality stays
unvalidated until the human gold sheet (`docs/extraction_gold_sheet.csv`) is filled; the evidence check is a proxy. Person A's 42 questions remain the unbiased test.

---

# Results (appended 2026-11-14; the rule above was committed first, in `41fdc5e`, and is unchanged apart from the corrected count "6 EXTEND + 7 NEW" in a docs commit before any measurement)

Command: `python -m knowledge_graph.evaluate_vocabulary_extension` (decisions written with `--apply`); dev sets with `FX_GRAPH_A=<graph before> FX_GRAPH_B=<graph after> python hybrid/evaluate_fixes.py fx3_overlay`.
No phrase was changed after seeing any result. No phrase was a hub (no single phrase matched more than 14 documents), so the phrase hub rule dropped nothing.

## Per-concept table (all 148 documents)

| concept | status | documents matched | newly covered | growth over existing group | evidence in body | decision |
|---|---|---|---|---|---|---|
| Device Compatibility | EXTEND | 4 | 2 | 1 | 4/4 | KEEP |
| Billing & Invoices | EXTEND | 7 | 0 | 5 | 7/7 | **DROP**: (a) growth 5 > 2 |
| Network Outages | EXTEND | 3 | 1 | 0 | 3/3 | KEEP |
| Security & Fraud | EXTEND | 6 | 1 | 0 | 6/6 | KEEP |
| SIM Card Services | EXTEND | 1 | 1 | 1 | 1/1 | KEEP |
| Enterprise & Business Services | EXTEND | 4 | 0 | 3 | 4/4 | **DROP**: (a) growth 3 > 2 |
| IoT & M2M Services | NEW | 3 | 3 | 3 (no existing group) | 3/3 | KEEP |
| Privacy & Data Protection | NEW | 3 | 2 | 3 | 3/3 | KEEP |
| International Calling & ISD | NEW | 1 | 0 | 1 | 1/1 | **DROP**: (b) a NEW concept must link at least 2 documents |
| Account Closure & Deactivation | NEW | 13 | 3 | 13 | 13/13 | KEEP (limit 14) |
| Fair Usage Policy (FUP) | NEW | 7 | 1 | 7 | 7/7 | KEEP |
| Connectivity Troubleshooting | NEW | 3 | 1 | 3 | 3/3 | KEEP |
| Accessibility & Communication Preferences | NEW | 2 | 1 | 2 | 2/2 | KEEP |

(Growth for a NEW concept is informational: the 2-document growth limit is for existing concepts.) Recorded in `knowledge_graph/vocabulary_extension.json` under `dropped`; the dropped rules stay in the file.
The rule-(c) check is a **proxy**: it re-applies the matcher to the body and cannot detect a wrong sense.

## Acceptance

- (a) met for every kept concept: at most 13 documents (limit 14); EXTEND growth at most 1 (limit 2). Billing & Invoices and Enterprise & Business Services were dropped for growth, as the rule says.
- (b) met: every kept NEW concept links at least 2 documents; International Calling & ISD (only FAQ_C11_021) was dropped.
- (c) met: 100% of the new edges have their evidence phrase in the body (proxy).
- (d) **documents with a content concept: 129 -> 144.** Sixteen documents are newly covered; one document loses its concept, FAQ_C11_022, by the exclusion (FAQ_C09_017 stays covered through the new FUP concept).
  **Still uncovered (4):** `FAQ_C11_021` (International Calling dropped: one document), `FAQ_C11_022` (excluded), `FAQ_C23_045` (Enterprise dropped), `INC_C04_INC_2026_0163` (Billing dropped).
- (e) dev sets, graph before vs after (52 questions, graph and links on): **top 5 identical for all 52**, 0 losses and 0 gains at R@1, R@3, R@5, pooled R@1 0.8269 / R@3 0.9423 / R@5 0.9615 / MRR@5 0.8756 in both arms,
  incident pairs 3/5 vs 3/5. Two graph builds are byte-identical (`graph.json`, `nodes.json`, `edges.json`, `content_extraction.json` compared). `graph.json`: 339 -> 345 nodes (6 new Concept nodes with `source="vocabulary_extension"`),
  1697 -> 1739 edges (`MENTIONS_CONCEPT` 7 -> 49). `MENTIONS_CONCEPT` is not a bridge of `graph_expand`, so nothing could move; the measurement confirms it.

## Step 3 - exclusions

`FAQ_C11_022 -> Network Coverage` and `FAQ_C09_017 -> Device Compatibility` are in the overlay's `exclusions` list with a reason each; both pairs are gone from the extraction and no other earlier edge moved (the five other Network Coverage edges
and FAQ_C12_023 remain). The name-family rules that produced them are not deleted.

## Matches the evidence file did not list (possible wrong senses) - reported, not tuned

All 56 listed (concept, phrase, document) triples match. In addition 43 matches appear in other documents; most are the same topic (e.g. `phishing` in the Phishing RCA and the fraud SOP, `FUP` in the tariff documents). The ones to look at:
- **Account Closure & Deactivation** (the widest new concept, 13 documents): `deactivate` / `deactivated` also fire in `FAQ_C10_019`, `SOP_C10_VAS_DISPUTE`, `TRN_001` (deactivating a VAS), `SOP_C05_SIM_REPLACEMENT` (deactivating the old SIM), `EML_001` (a service
  deactivated after a refund) and `MAN_ESIM_001` (the physical SIM is deactivated). These are probably the wrong sense: about six of the 13 documents are not about closing an account. The rule keeps the concept (it is under the limit and every phrase is in the body);
  a human should review it on the gold sheet. I did not drop the phrases, because the rule drops a phrase only for being a hub.
- **Connectivity Troubleshooting**: `Airplane Mode` fires in `SOP_C13_APP_ACCESS_ISSUES` (app login troubleshooting, not connectivity).
- **Device Compatibility**: `VoLTE` fires in `REL_2026_06` (a release note on VoLTE band expansion; plausible but not a compatibility document) and `IMEI` in `FAQ_C12_023` (listed expectation was MAN_DEVICE_VOLTE_001 only; plausible).
- **Billing & Invoices** (dropped anyway): `duplicate charges` in `FAQ_C20_039` and `Policy_C20_refund_policy`, `final bill` in `TRX_008`.
Full list with snippets: `knowledge_graph/output_hardening/fx3_unexpected.json` (gitignored; regenerated by `unexpected_matches` in `knowledge_graph/evaluate_vocabulary_extension.py` against `docs/gap5_vocabulary_evidence.csv`, which is a transcription of the supplied evidence file - only its concept / phrase / document triples are used).

## Tests (step 5) - hard-coded counts changed

`knowledge_graph/tests/test_concept_nodes.py`: `test_counts_23_concepts_and_33_expresses_edges` (concept nodes 23 -> 23 shared + 6 overlay = 29), `test_graph_json_has_the_concept_layer` (Concept labels 23 -> 29, `MENTIONS_CONCEPT` 7 -> 49,
nodes 337 - 21 + 23 -> + 6), `TestGraphIndexConceptAccessors.test_concepts_list` (23 -> 29). `knowledge_graph/tests/test_concept_mentions_graph.py`: the graph builder inside `build_to` now also switches the overlay off, so those tests keep isolating the
name-family mechanism (no count changed). New: `test_vocabulary_overlay.py` (14), `test_vocabulary_extraction.py` (16), `test_vocabulary_exclusions.py` (5), `test_vocabulary_acceptance.py` (17, including the real-corpus outcome and the
check that the recorded decisions equal a fresh evaluation). All other tests pass unchanged.

## Note for Person A

- What changed on our side: an overlay file `knowledge_graph/vocabulary_extension.json` (proposed, pending ontology-owner approval; the shared `ontology/` is untouched) gives 6 new `Concept` nodes (`source="vocabulary_extension"`) and 42 more
  `MENTIONS_CONCEPT` edges, and two doubtful edges from KG fixes 2 are removed. Documents with a content concept: 129 -> 144.
- Nothing in retrieval should move: on the dev sets 0 of 52 top-5 lists changed, and `graph_expand` does not read `MENTIONS_CONCEPT`. Your `_read_related_edges` reads the same `RELATED_TO` edges as before (105 edges, 47 undirected resolvable pairs).
- `graph.json` is generated and not tracked: run `python -m knowledge_graph.graph_builder` after pulling (and `python -m knowledge_graph.build_related_aliases` if the alias files changed on your side; they did not change here).
- Open for you and the ontology owners: approval of the overlay (the 3 dropped concepts can be revisited with new evidence), and a human review of `Account Closure & Deactivation` and the gold sheet.

## What is NOT shown

The dev sets are the sets everything was developed on, so "no change" is not generalisation evidence and differences below one question cannot be resolved. **Extraction quality is still unvalidated until the human gold sheet
(`docs/extraction_gold_sheet.csv`) is filled**: the evidence check is a proxy that cannot fail, and the Account Closure & Deactivation phrases visibly match other senses. The 144 figure counts documents with an edge, not documents with a
correct edge. Person A's 42 questions remain the unbiased test and were not used.
