# Reply to Person B on the KG fixes stack (2026-11-14)

Hi, thanks for the update. I checked everything against the repo today (details at the bottom). Short version of my decisions:

1. **Overlay concepts: accepted as an overlay only; the shared ontology IDs stay unchanged.** The overlay file carries no IDs, only names, and nothing
   in `ontology/*.json` is modified, so there is no ID collision. Two things before I treat the overlay as final: (a) your message names 5 new
   concepts, the file has 7 (`International Calling & ISD` and `Connectivity Troubleshooting` are the other two, both dropped by your own rule (b)),
   and 6 extended concepts of which 2 are dropped by rule (a), so I count 5 new + 4 extended active, not 5 + 5; please confirm which set is live.
   (b) Three NEW names are already category names in the shared schema (`International Calling & ISD` = C11, `Privacy & Data Protection` = C19,
   `IoT & M2M Services` = C24). Not an ID collision, but a name collision that the join-on-name accessors in `graph_augmented_retrieval` would
   feel; please tell me whether that is intended. And for each live concept, which questions or documents it is for.
2. **The 16 dangling `KB_Cnn_overview` links: drop them from the graph and log them.** None of the 8 categories (C01, C10, C11, C12, C14, C15, C24, C27)
   has any KB document on my side (raw files, processed documents, or the FAISS index), so no stand-in exists, and I will not write new overview
   documents: that would change the corpus every published number was measured on. Your option 3, with the 16 recorded in docs.
3. **The "`FAQ_Cnn_001` = whole category" assumption.** Evidence: every category has exactly 2 FAQs, numbered globally (C02 has 003/004, ... C29 has
   057/058); `FAQ_Cnn_001` exists only for C01. So "001" cannot be a real document for 21 of the categories, which is consistent with a placeholder,
   but nothing in the data says whether the author meant "the first FAQ of the category" or "all FAQs". Undetermined. Proposal: keep your alias
   rule but emit those 21 edges as a distinct inferred type (for example `RELATED_TO_INFERRED`, or a `rule` property on the edge) so an ablation can
   switch them off; my `semantic_layer.py` reader filters on `type == "RELATED_TO"` today, so it would ignore them until I opt in.
4. **Guard tests.** Confirmed on the combined checkout: 6 failures, all expected and all from your structured-side changes. Q04 is the parser
   change you describe: the old parser read "paid" inside "postpaid" and filtered invoices on `payment_status = 'Paid'`; the new one finds the
   table but no filter and returns no rows. I will report it as a parser change, not a retrieval change. The other 5 are the `route` /
   `executed` status contract in `customer_scoped_filter` versus my guard's expectations; nothing is fixed on either side yet.
5. **Graph for my re-run.** I will run on branch `person-a/pinned-rerun`, commit `86d2802` (= your `e29f010` merged with my `0395c5a`, no conflicts),
   with **frozen graph v1** at `data/experiments/frozen_graph_v1/graph.json`, sha256 `7d56dac7e787f0d91e57350e2f149a4847f6dedf1e3facf8f1176239ed17790f`
   (337 nodes, 1,636 edges, 84 RELATED_TO of which 47 resolve). Please do not rebuild `graph.json` until I tell you the run is done. Your
   document-specific extraction change will be graph v2 and a separate experiment; v1 and v2 results will both be kept.

One thing you should know about v1: it is the graph built on 2026-11-10 at the kg-hardening code state. It has **no Concept nodes and no
`EXPRESSES_CONCEPT` / `MENTIONS_CONCEPT` edges**, so the concept metadata and the overlay from fixes 3 to 6 are not in it. Your code at `e29f010`
reads such a graph fine (the accessors return empty). If you want the re-run to exercise the concept layer, that is a rebuild with your current
builder, which I would then freeze as a different version; tell me which you prefer before I start.

Thanks for the careful handoff notes; the pre-declared rules and the "AI-labelled, human review pending" wording made the verification easy.

---

## Evidence (what I verified, in the repo at `86d2802`)

* **Branches.** `e29f010` = `origin/person-b/kg-fixes6`; `0395c5a` = `exp/kg-hardening-eval` (local and origin). Neither is an ancestor of the other;
  merge base `700a5dd`. `person-b/kg-hardening` has moved to `4956b37`, which is an ancestor of `e29f010`. `main` is unchanged at `f2249a6`.
  `kg-fixes6` changes 71 files (docs, knowledge_graph, hybrid, scripts, tests) and nothing under `integration/`, `structured/`, `query_router/`.
* **Overlay** (`knowledge_graph/vocabulary_extension.json`, status "proposed, pending ontology-owner approval"). NEW (7): IoT & M2M Services;
  Privacy & Data Protection; International Calling & ISD; Account Closure & Deactivation; Fair Usage Policy (FUP); Connectivity Troubleshooting;
  Accessibility & Communication Preferences. EXTEND (6): Device Compatibility; Billing & Invoices; Network Outages; Security & Fraud; SIM Card
  Services; Enterprise & Business Services. `dropped`: Billing & Invoices (rule a), Enterprise & Business Services (rule a), International Calling
  & ISD (rule b), Connectivity Troubleshooting (rule b). Entries have `concept`, `status`, `trigger_phrases` only; no ids. Trigger phrases are in
  the file; `narrowed_phrases` removed bare "deactivate"/"deactivated" and "Airplane Mode". `ontology/ontology_schema.json` lists the three NEW
  names under `category_catalog` C11 / C19 / C24.
* **Dangling links** (`docs/requests_for_PersonA.md`): FAQ_C01_001, FAQ_C01_002 -> KB_C01_overview; FAQ_C10_019, FAQ_C10_020 -> KB_C10_overview;
  FAQ_C11_021, FAQ_C11_022 -> KB_C11_overview; FAQ_C12_023, FAQ_C12_024 -> KB_C12_overview; FAQ_C14_027, FAQ_C14_028 -> KB_C14_overview;
  FAQ_C15_029, FAQ_C15_030 -> KB_C15_overview; FAQ_C24_047, FAQ_C24_048 -> KB_C24_overview; FAQ_C27_053, FAQ_C27_054 -> KB_C27_overview.
  No `KB_Cnn_overview` file exists under `data/` (raw or processed) and none is in my FAISS index (`combined_retrieval/vectorstore/chunk_metadata.json`);
  the 8 categories have no KB document at all on my side. The 16 source FAQs do exist (`data/raw/unstructured/faq/`).
* **FAQ numbering**: 29 categories x 2 FAQs, ids 001 to 058 global; only C01 has a real `FAQ_C01_001`. The 21 placeholder links in
  `knowledge_graph/related_id_alias_audit.csv` (rule `faq_placeholder_all_in_category`, flagged ASSUMPTION) all point to categories whose real
  FAQ ids are not 001.
* **Guard tests** (`integration/tests/test_structured_guard.py`, 13 tests + `test_rag_defaults_identical.py`): 6 failed / 8 passed in 113 s:
  `test_msisdn_keyed_table_is_answered_through_the_customers_msisdn` (route direct vs msisdn_mapping), 2x
  `test_table_with_no_customer_or_msisdn_column_is_reported_not_executable` (executed True), `test_unknown_customer_on_an_msisdn_table_is_reported_with_the_reason`
  (executed True), `test_e14_adapter_uses_the_guard_and_exposes_the_status` (route direct), `test_default_prompts_identical_to_head` (Q04). Old parser at
  `dc481b6` on Q04: `{'table': 'invoices', 'method': 'exact_filter', 'filter_column': 'payment_status', 'filter_value': 'Paid'}`; new parser:
  `{'table': 'invoices', 'method': 'exact_filter_unresolved', 'error': 'No specific filter identified'}`.
* **Graph**: `knowledge_graph/output/graph.json` is untracked (`.gitignore` line 23), 600,690 bytes, mtime 2026-11-10 20:19 local, sha256 above,
  schema_version 2.0.0, labels Document 177 (148 canonical + 29 stubs), Tag 68, Category 30, Service 14, Department 13, DocumentType 13, Channel 5,
  VerificationMethod 5; edges 1,636 incl. RELATED_TO 84. Readers: `integration/rag/semantic_layer.GRAPH_JSON`, `integration/qa/retrieval.py`,
  `hybrid/setup_check.py`, `knowledge_graph/graph_builder.GRAPH_JSON_PATH` all name `knowledge_graph/output/graph.json`; `hybrid/evaluate_fixes.py`
  additionally takes `FX_GRAPH_A` / `FX_GRAPH_B` paths. Frozen copy and manifest: `data/experiments/frozen_graph_v1/MANIFEST.json`.
