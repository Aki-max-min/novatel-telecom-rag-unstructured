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
