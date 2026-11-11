# E13 KG fixes 2 - rules (pre-declared) and results

Audit gaps 5 (23 documents without a content concept), 6 (RELATED_TO links), 7 (extraction never validated) and 8 (query enrichment), from our side only.
Branch `person-b/kg-fixes2`, started from the final head of `person-b/kg-fixes` (`01cc233`). Each step: rule here (committed before any measurement),
tests first, then the change, separate commits. **Results are appended below the rules; the rules are not edited afterwards.**

Hard limits: nothing under `integration/`, no edit of `data/processed` documents or their `related_ids`, the Common Result Schema or frozen benchmark files; no import from
`integration/`; no LLM, no embeddings, no new retrieval layer. Dev sets only (main 29, mini 9, validation 14 = 52 questions, plus the 5 incident pairs in
`hybrid/benchmark/incident_link_check.json`); Person A's 42 questions are never used.

## Step 0 - recon findings (read-only, facts that shape the rules)

- `content_extractor.py` ALREADY scans the full `title` and `content` of every document, not only a summary. The 23 documents without a concept (17 FAQ, 3 INC,
  2 MAN, 1 EML) are therefore vocabulary gaps (VoLTE, IoT/M2M, privacy, international rates, deactivation, data speed ...), not unread text. "Extend the rules to read
  FAQ answer text" has no literal meaning here; the only lever that stays inside the existing vocabulary is more phrases from that vocabulary.
- The corpus carries template echoes of the category name: every non-FAQ document has a metadata header (`**Document ID:** ... **Category:** C04 - Billing & Invoices ...`)
  and every FAQ ends with `Topic: <category name>`. A concept-name rule that reads them would just re-derive the Category node. Rules below read the body only.
- The ontology has no synonym lists. Existing vocabulary = the 23 shared concept names (`concept_bridge.concept_vocabulary`), `SERVICE_CONCEPT_MAPPING`, the trigger phrases of
  `CONCEPT_DICTIONARY`, the category catalogue names, and `hybrid/query_gate.KEYWORD_CONCEPT_MAP` (our own keyword -> concept map, validated against the vocabulary).
- `RELATED_TO` aliases (`build_related_aliases.py`) are a single-valued map (original target -> one document). The 21 `KB_Cnn_*` -> `FAQ_Cnn_001` links need a one-to-many map.
- Person A's `normalise_query` (read-only, `integrate/kg-ontology-router-ui`): in plain words, it classifies the question with OUR gate to get one concept hint, then appends
  the concept name and the names of the document categories the crosswalk links to that concept to the text sent to FAISS; the CrossEncoder still sees the original question.
  Hers is OFF by default. Ours (step 4) is a separate module and will not import hers.

## Step 1 rule - gold sheet (preparation only; a human must fill it)

`docs/extraction_gold_sheet.csv`: 20 documents. Selection rule (seed 20260611, `random.Random`): (1) one document each from categories C11, C12, C24 (the three categories
with no concepts), drawn from the document types below; (2) the rest stratified by document type with quotas FAQ 4, KB 3, SOP 3, INC 3, MAN 3, EML 2, TRN 2 (total 20, forced
picks count towards their type's quota); candidates sorted by id, shuffled by the seeded generator, no document twice. The human columns `correct_concepts` and `notes` are
written EMPTY and are never filled by us; model output is never gold. A row is "unreviewed" until `correct_concepts` is non-empty; a human writes `NONE` for "no concept".
`scripts/score_extraction_gold.py` prints per-label precision, recall and the disagreements from a filled sheet (a test uses a tiny fake sheet).
The automatic evidence check (every predicted concept's evidence phrase is present in the document text) is reported as a **precision proxy only: the extractor's own
rule re-applied, it cannot detect a wrong sense, so it is not validation.**

## Step 2 rule - concept phrases for documents without a concept

Rule family = the exact name of one of the 23 shared concepts used as a trigger phrase (boundary-safe, case-insensitive, same matcher as the extractor) on the BODY of a
document (title + content with the metadata header lines and the trailing `Topic:` footer removed). A hit writes a `MENTIONS_CONCEPT` edge Document -> existing `Concept` node
with the evidence phrase, field and snippet. One family per concept, one commit per family, added in alphabetical order. The `GraphIndex` bridges (Service, Channel,
VerificationMethod, Tag) do not read this edge type, so retrieval cannot change through it; (d) verifies that.
Acceptance, ALL must hold:
- (a) the number of documents with at least one content concept (any `MENTIONS_*` edge) rises from 125;
- (b) no concept appears in more than 10% of the 148 documents (more than 14) and no concept hub grows by more than 2 documents, where growth = documents that mention the
  concept in the body but are not already in its category/service document group;
- (c) 100% of new edges pass the evidence check;
- (d) at the end: no dev question lost at R@1, R@3 or R@5 versus the state before this step, and two graph builds are byte-identical.
Per family: kept only if (b) and (c) hold AND it newly covers at least one document that no earlier kept family covers (otherwise it adds edges without closing the gap);
a family that breaks (b) is dropped and reported. If no family survives, the extractor is left unchanged and that is the result.

## Step 3 rule - RELATED_TO aliases (our alias layer only)

The 21 `KB_Cnn_*` -> `FAQ_Cnn_001` links: ASSUMPTION (flagged in the audit csv, rule `faq_placeholder_all_in_category`): "001" is a placeholder for the category's own FAQs, so the
link resolves to every FAQ document of category Cnn in the corpus (two per category). The 16 `FAQ_Cnn_*` -> `KB_Cnn_overview` links (C01, C10, C11, C12, C14, C15, C24, C27)
stay UNRESOLVED; no link to any other document is invented. `docs/requests_for_PersonA.md` lists them with three options for her. Source documents are untouched.
**Keep the 21-link mapping only if no dev question is lost at R@1, R@3 or R@5 and the incident pairs are not worse**; otherwise the alias file is left as before and
the finding is reported. Reported either way: new resolved count, new maximum document degree, any new hub. Tests that hard-code 47/37 are updated and listed.

## Step 4 rule - query enrichment (`hybrid/enrich.py`)

`enrich_query(question) -> (enriched_text, trace)`; deterministic. For each ontology concept recognised in the question (our gate's matcher), append its canonical name and its
synonyms from the existing vocabulary (trigger phrases of the services mapped to it in `SERVICE_CONCEPT_MAPPING`, and `KEYWORD_CONCEPT_MAP` keywords for it), at most 6 appended
terms in total, original words never removed or reordered; no match -> enriched == original. The enriched text goes to the FAISS query ONLY; CrossEncoder, gate, router and
the structured parser always get the ORIGINAL question. `ENRICH_ENABLED` defaults to False; trace field `enrichment`. Tests first (identity, cap, order, structured path
unchanged, off = byte-identical output). Measurement: off vs on over the 52 dev questions. **Set `ENRICH_ENABLED=True` only if no question is lost at R@1, R@3 or R@5 and at
least one gains; otherwise it stays False and the losers are reported with their traces.**
Out of scope, with reasons: metadata-aware boosting (it would be a new ranking signal, i.e. a new retrieval layer, and the audit found the fusion cannot be tuned on 52 questions);
ColPali (needs a vision model and page images, not deterministic text rules, no embeddings allowed).

## What is NOT shown (stated up front)

The dev sets are the sets everything was developed on, so a verdict is not generalisation evidence and differences below one question cannot be resolved. The gold sheet is
unfilled, so extraction quality remains unvalidated whatever the proxy says. Person A's 42 questions stay the unbiased test.
