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

---

# Results (appended 2026-11-11; the rules above were committed first, in `238920b`, and are unchanged)

All dev-set runs: 52 questions (main 29, mini 9, validation 14), graph and links on, default rerank mode, same CrossEncoder scores in both arms; command
`python hybrid/evaluate_fixes.py fx2_stepN` with `FX_GRAPH_A` / `FX_GRAPH_B` for the graph arms; raw output `knowledge_graph/output_hardening/fixes_fx2_step*.json` (gitignored).

| Step | Gap | Result | Verdict |
|---|---|---|---|
| 1 | 7 | `docs/extraction_gold_sheet.csv` prepared (20 documents, seed 20260611), human columns EMPTY; scorer + tests; evidence proxy 385/385 | prepared, **not validated** |
| 2 | 5 | 2 of 23 concept-name families kept; documents with a content concept 125 -> 129; 19 documents still without | partial |
| 3 | 6 | 21 KB -> FAQ placeholder links resolved; related ids resolved 47 -> 68 of 84; dev sets: 0 of 52 top-5 lists changed | KEEP |
| 4 | 8 | enrichment: R@1 0.8269 -> 0.7308, 6 losses at R@1 and 1 at R@3, 1 gain at R@1 and 1 at R@5 | `ENRICH_ENABLED` stays False |

## Step 1 - gold sheet (prepared, needs a human)

20 documents drawn by the declared rule - FAQ_C11_022, FAQ_C12_024 and MAN_IOT_PORTAL_001 for the three categories without concepts (C11, C12, C24), the rest
stratified (FAQ 4, KB 3, SOP 3, INC 3, MAN 3, EML 2, TRN 2). Columns as specified; `correct_concepts` and `notes` are empty in every row (checked). The sheet lists the five
original labels and the new `Concept:` body-mention predictions, so a human can judge both. A row with a blank `correct_concepts` counts as not reviewed; write `NONE` for
"no concept". `python scripts/score_extraction_gold.py` prints per-label precision, recall and the disagreements; on the unfilled sheet it prints "No reviewed row" and exits 1.
Tests: `knowledge_graph/tests/test_gold_sheet.py` (11, including a tiny fake filled sheet).
**Evidence check, a precision PROXY and not validation:** 385 of 385 predictions have their evidence phrase in the document text. It is the extractor's own matching rule applied
again, so 1.0 is guaranteed by construction and says nothing about wrong senses. One thing it did reveal: 2 of the 378 original predictions have evidence only in the template footer
(`FAQ_C13_025` Self-Care Portal, `FAQ_C17_033` Photo ID, found by reading the body only); they are left as they are (existing edges, not touched by this step).

## Step 2 - concept-name families (gap 5)

**The premise needs a correction.** The extractor already reads the full title and content of every document, FAQ answers included. The 23 documents without a concept (17 FAQ,
3 INC, 2 MAN, 1 EML) are a *vocabulary* gap: their subjects (VoLTE, IoT/M2M, privacy, international rates, deactivation, data speed, coverage gaps ...) have no concept in the
shared vocabulary or in the document dictionary, and the rule forbids inventing vocabulary. The only lever inside it was the exact names of the 23 shared concepts, read on the body
(the metadata header and the `Topic:` footer are category-name echoes and were excluded; matching them would have "covered" most of the 23 with the Category node's own name).
One family per concept, alphabetical; per-family check `python -m knowledge_graph.evaluate_concept_families`:

| concept | docs mentioning | group size | growth | newly covered | (b) | verdict |
|---|---|---|---|---|---|---|
| Billing & Invoices | 3 | 7 | 0 | 0 | ok | drop (covers nothing new) |
| Broadband & FTTH Services | 3 | 11 | 0 | 0 | ok | drop |
| Complaints & Grievances | 2 | 45 | 0 | 0 | ok | drop |
| Customer Account | 1 | 16 | 0 | 0 | ok | drop |
| **Device Compatibility** | 2 | 3 | 1 | 2 | ok | **KEEP** (commit a7c81c0) |
| Enterprise & Business Services | 2 | 5 | 0 | 0 | ok | drop |
| Field Operations, Offers & Promotions, Plan Catalogue, Retail & Store Network, Usage Records | 0 | - | 0 | 0 | ok | drop (no body mention) |
| KYC & Identity Verification | 3 | 30 | 0 | 0 | ok | drop |
| **Network Coverage** | 5 | 9 | 1 | 2 | ok | **KEEP** (commit 4a5677a) |
| Network Outages, New Connection Activation, Number Portability, Payments, Roaming, SIM Card Services, Security & Fraud, Value Added Services | 1-9 | - | 0 | 0 | ok | drop (cover nothing new) |
| Recharge | 16 | 17 | 0 | 0 | **fails: 16 > 14 (10% of 148)** | drop |
| Subscription | 4 | 5 | 4 | 0 | **fails: growth 4 > 2** | drop |

Kept: Device Compatibility -> FAQ_C09_017, FAQ_C12_023 (newly covered); Network Coverage -> FAQ_C08_015, FAQ_C11_022 (newly covered) plus KB_C08_outage_status_check,
RCA_INC_2026_0142, SOP_C08_OUTAGE_MANAGEMENT. 7 `MENTIONS_CONCEPT` edges in all, each with evidence phrase, field and snippet.
Acceptance: (a) 125 -> 129 documents with a content concept - **met but small**; (b) max 5 documents per concept (limit 14), hub growth 1 and 1 (limit 2) - met;
(c) evidence 7/7 on the body - met; (d) dev sets: **0 of 52 top-5 lists changed**, 0 losses, 0 gains, incident 3/5 vs 3/5; two graph builds byte-identical (test) - met.
`MENTIONS_CONCEPT` is not a bridge of `graph_expand`, so it cannot move retrieval; (d) confirms it. Against us: **19 of the 23 documents still have no content concept**
(EML_005, FAQ_C04_008, FAQ_C09_018, FAQ_C11_021, FAQ_C12_024, FAQ_C19_037/038, FAQ_C21_041/042, FAQ_C23_045, FAQ_C24_047/048, FAQ_C29_057/058, INC_C04_INC_2026_0163,
INC_C08_INC_2026_0142, INC_C18_INC_2026_0197, MAN_DEVICE_VOLTE_001, MAN_IOT_PORTAL_001); closing them needs new vocabulary (a decision for the ontology owners, not a rule change).
Two kept edges are doubtful senses and are on the gold sheet or easy to review: FAQ_C11_022 ("out of network coverage in my recipient's country" is about international calls) and
FAQ_C09_017 (device compatibility is one of several causes of slow data). The extractor tests (new: `test_content_extractor.py`, 18) pin the previous behaviour as well.

## Step 3 - RELATED_TO aliases (gap 6)

ASSUMPTION flagged in `knowledge_graph/related_id_alias_audit.csv` (new `note` column): `FAQ_Cnn_001` = a placeholder for the category's FAQs, resolved to every FAQ of category Cnn
(two each). Switch `RESOLVE_FAQ_PLACEHOLDER` in `build_related_aliases.py`; one-to-many `multi_aliases` in `related_id_aliases.json`; both extractors emit one edge per target.
- Resolved related ids: 47 -> **68** of 84; unresolved 37 -> 16 (the KB overview links of C01, C10, C11, C12, C14, C15, C24, C27, listed in `docs/requests_for_PersonA.md`
  with three options for her; nothing is linked to any other document). Stub nodes 29 -> 8.
- Directed RELATED_TO edges 84 -> 105; resolved directed edges 47 -> 89.
- **Undirected resolved pairs 47 -> 47, documents with links 73 -> 73, maximum document degree 2 -> 2, no new hub.** Against us (or at least not for us): the 21 links add no new
  neighbour; each KB -> FAQ pair is already connected by the reverse FAQ -> KB link that the existing KB-overview alias resolves. What changes is the direction and the resolved count.
- Dev sets: 0 of 52 top-5 lists changed, 0 losses, 0 gains, incident 3/5 vs 3/5. Rule (no loss, incident not worse) met -> kept.
- Tests that hard-coded the old counts and were changed (all in `knowledge_graph/tests/`): `test_related_aliases.py` - `test_expected_counts` (47/37 -> 68/16, rule counts, FAQ unresolved 21 -> 0),
  `test_related_edges_resolve_47_and_leave_37_stubs` (84/47/37 -> 84/68/16, edges 84 -> 105, via_alias 47 -> 89, unresolved edges 37 -> 16, stubs only KB), `test_rebuilt_graph_json_yields_47_resolvable_pairs`
  (pairs 84 -> 105, resolvable 47 -> 89 directed), `test_committed_alias_files_match_a_fresh_build` (audit csv has the sixth column `note`);
  `test_concept_nodes.py` - `test_graph_json_has_the_concept_layer` (base nodes 337 -> 316 because 21 stubs became real links, RELATED_TO 84 -> 105, base edges 1636 + 21 + 33, plus the 7 mention edges counted separately) and
  `test_person_a_reader_and_incident_pairs_read_the_new_graph_unchanged` (105 pairs, 89 resolvable directed); `test_concept_mentions_graph.py` (RELATED_TO 84 -> 105). All other tests
  (including the 47 undirected `GraphIndex` links in `test_graph_expand.py`) pass unchanged. `graph.json` is now 339 nodes / 1697 edges (316 base + 23 concept nodes; 1636 + 21 + 33 + 7 edges).

## Step 4 - query enrichment (gap 8)

`hybrid/enrich.py`; `ENRICH_ENABLED=False` in `pipeline.py`; trace field `enrichment` exists only when it is on (so off is byte-identical, trace included); tests `test_enrich.py` (15).
Dev sets, arm A = original question to FAISS, arm B = enriched text to FAISS only:

| | R@1 | R@3 | R@5 | MRR@5 |
|---|---|---|---|---|
| A pooled | 0.8269 | 0.9423 | 0.9615 | 0.8756 |
| B pooled | 0.7308 | 0.9231 | 0.9808 | 0.8308 |

Per set R@1 (A -> B): main29 0.9310 -> 0.8621, mini9 0.4444 -> 0.3333, validation14 0.8571 -> 0.7143. Top 5 changed for 31 of 52 questions. Losses (A hits, B does not): R@1 6, R@3 1, R@5 0;
gains: R@1 1, R@5 1. Incident pairs 3/5 vs 3/5. **Rule (no loss and at least one gain) not met -> `ENRICH_ENABLED` stays False.** Losers with their traces (concepts -> appended terms):
- "Money was deducted when I tried to recharge ..." (R@1): Recharge -> top-up, top up, validity extension.
- "My mobile internet has become much slower ... data usage limit" (R@1): Usage Records -> call record, call detail (wrong sense: this is about data speed, not call records).
- "I bought a new SIM but it still isn't active ..." (R@1): SIM Card Services -> esim, sim swap, swap the sim, sim replacement, replacement sim (pulls SIM-swap documents above the activation FAQ).
- "What record does the billing team keep about why refunds were given?" (R@1): Billing & Invoices, Payments -> invoice, payment, bill payment, pay the bill.
- "Does NovaTel offer any help for customers who can't hear well?" (R@1): Offers & Promotions -> promo, promotion (the verb "offer" fired the gate's keyword; wrong sense).
- "My latest bill is unpaid - if I don't pay, will my number get deactivated ..." (R@1 and R@3): Billing & Invoices -> invoice.
Gains: "If I move my existing number ... porting process" (R@1; Number Portability + synonyms) and "My KYC is showing pending ..." (R@5).
Cause, from the traces: the recognition uses the gate's keyword list, which has crude senses ("offer", "data usage", "record"), and the appended synonyms are the vocabulary's surface forms,
which add noise as often as signal. Not tuned afterwards (that would be fitting the dev sets).

Comparison with Person A's `SemanticLayer.normalise_query` (read-only; behaviour as documented in her module, not re-measured here):

| | Person A (`normalise_query`) | ours (`hybrid/enrich.py`) |
|---|---|---|
| concepts used | one: the gate's concept hint | every concept recognised in the question |
| appended | concept name + names of the document categories the crosswalk links to it | concept names, then vocabulary synonyms (gate keywords, service triggers); no category names |
| cap | none | 6 terms |
| already in the question | not checked | never repeated |
| used for | FAISS query only; CrossEncoder keeps the original | FAISS query only; CrossEncoder, gate, router, structured parser keep the original |
| default | off (`RagConfig.semantic_layer = False`) | off (`ENRICH_ENABLED = False`) |
| imports | our gate and crosswalk | our modules only; nothing from `integration/` |

Out of scope, as declared: metadata-aware boosting (a new ranking signal, i.e. a new retrieval layer) and ColPali (vision model, not deterministic text rules, no embeddings).

## What Person A needs to know

- **What changed on our side:** content extractor gains `MENTIONS_CONCEPT` edges (7) from Document to the existing Concept nodes; 21 `FAQ_Cnn_001` placeholder links now resolve to the category's two FAQs (alias layer only,
  flagged ASSUMPTION; `RESOLVE_FAQ_PLACEHOLDER=False` undoes it); `hybrid/enrich.py` exists but is OFF; the gold sheet exists but is unfilled. Nothing under `integration/`, `data/processed` or any benchmark file was touched.
- **What she must NOT expect to change in her results:** nothing in retrieval moves on our dev sets (0 of 52 top-5 lists changed for steps 2 and 3, enrichment is off). Her `_read_related_edges` reads the same RELATED_TO
  edges plus 21 more directed ones; the undirected resolvable pairs stay 47, so her related-link neighbours do not change. Her 42 questions remain the unbiased test.
- **graph.json is generated and not tracked.** After pulling, run `python -m knowledge_graph.build_related_aliases && python -m knowledge_graph.graph_builder`; until then her reader sees the older graph.
- **For her decision:** the three options for the 16 unresolved KB overview links (`docs/requests_for_PersonA.md`), and whether the "001 = placeholder" reading is right.
- **Open for a human:** the gold sheet. Extraction precision and recall are still unmeasured.

## What is NOT shown

The dev sets are the sets everything was developed on, so a "no change" verdict is not generalisation evidence and differences below one question cannot be resolved; the incident check is five pairs.
The gold sheet is unfilled, so **extraction quality is still not validated**: the 385/385 evidence figure is a proxy that cannot fail, and two of the seven new edges are doubtful senses.
Steps 2 and 3 show only that retrieval did not move, not that the extra edges or links help. Person A's 42 questions remain the unbiased test and were not used.
