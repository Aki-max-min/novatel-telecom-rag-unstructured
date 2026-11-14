# E13 hybrid layer - architecture status

Status of each stage of the pipeline on branch `person-b/hybrid-e13`, with the evidence and the known limitation.
"Built" = code exists. "Tested" = unit tests exist and pass (full suite: see the end). "Known limitation" cites the post-hoc
log (`docs/E13_phase8_posthoc_log.md`) wherever the limit comes from a post-hoc change or a measured miss.

```
question, customer_id (session), as_of
  -> [1] clause analysis + query gate  (hybrid/clauses.py, query_gate.py, textmatch.py)
  -> [2] router + identity / privacy guards  (hybrid/router.py)
        |-- structured channel: [3] customer-scoped read-only adapter  (hybrid/structured_adapter.py)
        '-- document channel : [4] vector + graph candidates -> [5] document-level RRF fusion + dedup
                                 -> [6] controlled CrossEncoder rerank          (retrievers.py, fusion.py, dedup.py, rerank.py)
  -> [7] context assembly: F1..Fn facts and D1..Dk documents, two separate channels  (hybrid/context.py)
  -> [8] answer: extractive (default) or LLM (off)  (hybrid/answer.py)
  -> [9] deterministic groundedness verifier  (hybrid/groundedness.py)
```

| # | Stage | Built | Tested | Known limitation |
|---|---|---|---|---|
| 1 | Clause analysis + gate (personal / policy / hypothetical; concept hint; graph weight 0.5 / 0.15 / 0.0) | yes | yes: shared-matcher property test (630 keyword checks), Phase 8 / 8d / 8e unit tests, 7 probes, new-sentence leak scans | Rule-based and a post-hoc fit (fixes 1-10 in the log). "when I tried ..." narrative reads as hypothetical and conditional inheritance swallows the next clause; personal context without a possessive or without a listed fact term is not detected; keyword concept hints are crude (see "Known limitations of the accepted router"). Query understanding is joint-design territory with Person A (roadmap Section 7). |
| 2 | Router: structured / unstructured / both; needs_identity; refuse_other_customer; third-party and other-number guards; unrecognised-request flag | yes | yes: router, Phase 8a fixes, probes, frozen benchmark runs (leakage 0 in every run) | The third-party rule refuses some policy questions ("merge my plan with my wife's"). Headline is the untuned first run (route 21/24, fact recall 23/30); amended-3 (24/24) is a post-hoc fit. No blind-set result yet. |
| 3 | Customer-scoped read-only structured adapter (5 intents, allow-listed fields, msisdn masked, derived flags labelled) | yes | yes: verified anchors, 25 customers x all intents = 0 leakage, read-only write attempts raise, parameterised-SQL scan | Stored values reported verbatim; the data has inconsistencies (Unpaid invoice with full SUCCESS payment; Active subscriptions with past expiry) that are surfaced as derived flags, never "fixed". Invoice answers do not include the charge breakdown (plan/usage/VAS/tax). |
| 4 | Vector + graph candidates (Person A's FAISS index, KG expansion) | yes (reused, not reimplemented) | yes: Phase 5 metrics reproduced exactly after the refactor | Document-level (best chunk per document). Graph candidates and links are ON by default in `run_hybrid_query` since the graph-fusion fix (see stage 5 and the correction below). |
| 5 | Document-level **append-only** fusion + dedup (graph-fusion fix): vector order kept verbatim; link-only then graph-only documents appended; `fusion_score` = 1/(k+position); weights are on/off switches | yes | yes: contract tests (`test_graph_append_only.py`, 8), updated arithmetic tests, 0-weight excludes concept candidates | The graph is a candidate source, never a ranker: ranking is the CrossEncoder rerank only. Graph and links are ON by default (dev sets: 0 losses at R@1/R@3, +1 at R@5; `docs/E13_graph_fusion_fix.md`). The gate still switches the concept list per question. No gain at R@1/R@3 is shown; Person A's 42 remain the unbiased test. |
| 6 | Controlled rerank: pool capped at 20; default V1 rrf_blend (w = 1.0) | yes | yes: pool-cap evidence, mode arithmetic tests, real CrossEncoder run | V1 was selected by a pre-declared rule whose macro-average over-weights the 9-question set (addendum in `docs/E13_phase8_rerank_selection_rule.md`); on pooled data V0 and V1 are indistinguishable. The shipping default is to be decided on a blind set (adopt V1 only if pooled MRR@5 beats V0 by >= 0.02). |
| 7 | Context assembly with notices | yes | yes | Snippets are cleaned only for line-start metadata headers; some documents keep an inline "Document ID: ... Category: ..." header in the snippet. Chunk boundaries can start a snippet mid-sentence. |
| 8 | Extractive answerer (default); LLM answerer behind one interface (off) | yes | yes: anchors for customers 1042 / 1056 / 1829, silence rule, notices, fake-LLM fallback tests (no network) | Quotes are whole sentences picked by token overlap, so they can be long or only loosely relevant. Model choice, prompt design and cost are a joint decision with Person A; no model is configured by default. |
| 9 | Deterministic groundedness verifier (5 rules) | yes | yes: 30 of 30 mutants of 6 grounded answers flagged by the expected rule | Checks citations, numbers/dates, masked identifiers and safety wording, not meaning: an uncited absence claim ("I found no tickets") or a wrongly-chosen quote passes. |

## Knowledge-graph hardening update (branch `person-b/kg-hardening`)

> **Correction (graph-fusion fix).** The hardening verdict (FAIL, graph OFF) and the link-decoupling verdict (FAIL, links OFF) below were measured with the buggy merge, in which graph membership added a score bonus large enough to outrank relevance (rank 1 = 0.01639 vs a 0.0025 / 0.0082 bonus). Fusion is now append-only and the graph/links are ON again per a pre-declared dev-set measurement (`docs/E13_graph_fusion_fix.md`). Those verdicts' candidate-level findings (hub audit, alias resolution) stand; their conclusions about the graph's value are superseded.


What the graph now does: `graph_expand` has hub-cut / specificity / cap / label options (legacy default unchanged, golden-tested); 47 of the 84 `RELATED_TO`
links now resolve through a deterministic alias file (`knowledge_graph/related_id_aliases.json`), so document-to-document links exist; resolved links are
loaded into `GraphIndex` and used as a "sibling" step placed first in the graph candidates (`hybrid/retrievers.py`); the structured retriever follows
allow-listed foreign keys (invoice -> payment_transactions, ticket -> escalation_cases) with customer scoping.

**What is OFF by default and why:** the graph list is excluded from fusion in `run_hybrid_query` (`GRAPH_ENABLED = False` in `hybrid/pipeline.py`, trace
"graph disabled by config"). The pre-declared 22-configuration evaluation on dev sets (`docs/E13_kg_hardening_rule.md`, `docs/E13_kg_hardening_results.md`)
failed its adoption rule: best pooled wins - losses +1, needed >= +2. The hub defect is real at the candidate level (72% of legacy candidates share only hub
concepts) but no downstream gain was demonstrated. The incident-link mechanism check showed no change (3/5 vs 3/5). Handoff: `docs/kg_hardening_for_personA.md`.

**Link decoupling (pre-declared, `docs/E13_link_decoupling_rule.md`): FAIL, links OFF by default.** Resolved RELATED_TO neighbours can now form their own fusion list (top-3 vector seeds, cap 2, `link_candidates`/`link_weight` in `hybrid/fusion.py`, `LINKS_ENABLED = False` and `links_enabled=` in `hybrid/pipeline.py`), independent of the gate graph weight - the trace had shown weight 0.0 for four of five incident questions. Result (`docs/E13_link_decoupling_results.md`): 0 wins / 0 losses in every cell on the dev sets and 3/5 vs 3/5 incident pairs, so no adoption. IL4 stays missed because its RCA is vector rank 4 and the rule seeds only the top 3; **IL1 is a reranker miss** (CrossEncoder rank 9 of 9), recorded as such and not changed.
Setup after cloning: `python -m knowledge_graph.graph_builder`, `python -m hybrid.setup_check`.

## Evidence

- Phase 5 (original design vs real benchmarks): the rerank, not the gate, produced the main-benchmark gain; no gain over Person A's existing reranker (`docs/E13_Hybrid_Fusion_Roadmap.md` Section 8).
- Frozen route benchmark (24 questions; `hybrid/benchmark/`): first run route 21/24, outcome 24/24, fact recall 23/30, leakage 0 (the headline); amended-1 / -2 / -3 are labelled post-hoc (`docs/E13_phase8_posthoc_log.md`).
- Answer layer (`hybrid/benchmark/answer_eval_phase9c.json`, extractive, deterministic): verifier 24/24, citation validity 24/24, fact inclusion 29/30, needs_identity and refusal safety items pass. Re-run after two post-hoc fixes: `answer_eval_phase9c_postfix.json` (same metrics; fixes logged below).

## Post-hoc fixes in the answer layer (found by reading sample answers, not by a metric)

1. With no customer, the extractive answer said "I found no recharges on your account" - false, since nothing was looked up. Absence sentences are now only produced for an identified customer.
2. Quotes could be unreadable markdown-table fragments. Sentences containing table markup are skipped and quotes over 450 characters are avoided when a shorter sentence exists.
The one fact-inclusion miss (RB_B06: the answer does not state `plan_charge`) was left as measured.

## Open items for the joint sync with Person A

- Whether and which LLM sits behind the answerer, with what prompt and cost budget (module docstring in `hybrid/answer.py`).
- Redesign of the gate's signal for graph-dependence (roadmap Section 8 open question 1) and graph-vs-rerank treatment (open question 2).
- The blind set: unwritten. It is the real generalisation test for the router and for the V1-vs-V0 rerank default.
- The `docs/` and `hybrid/` additions live only on this branch; nothing outside `hybrid/` and `docs/` was modified.

---

## Addendum 2026-11-11 (KG fixes)

- **Stage 4 numbers no longer reproduce.** The stage-4 figures were produced before the single link mechanism: today `run_hybrid_query` uses `use_related_links=False`, so re-running the old evaluation gives the numbers in `docs/E13_kg_fixes.md` (pooled dev R@1 0.8269, R@3 0.9423, R@5 0.9615, MRR@5 0.8756; the link change itself did not move the top 5 of any of the 52 dev questions).
- **Stage 5 (graceful degradation and concept metadata).** A missing `graph.json`, model/FAISS assets or structured database no longer raises: the pipeline returns what remains, with trace notes. The graph carries 23 concept nodes with table names; the context and trace expose `concept`. The blend (`rrf_blend`) and the legacy graph profile were re-tested and kept. Gate tiers 0.5/0.15, `LINK_WEIGHT` and `VECTOR_WEIGHT` are switches, not weights. See `docs/E13_kg_fixes.md`.

---

## Addendum 2026-11-11 (KG fixes 2, branch `person-b/kg-fixes2`)

- Stage 4 (candidates): the graph gains 7 `MENTIONS_CONCEPT` edges (Document -> Concept, body only) and 21 more resolved `RELATED_TO` edges (21 `KB_Cnn_*` -> `FAQ_Cnn_001` placeholder links resolved to the category's two FAQs, an ASSUMPTION; the undirected resolvable pairs stay 47). Neither is read by `graph_expand` as a bridge, and the 52 dev questions show 0 changed top-5 lists.
- Query enrichment (`hybrid/enrich.py`, FAISS query only) exists behind `ENRICH_ENABLED=False`: on the dev sets it lost 6 questions at R@1 and 1 at R@3 against 1 gain at R@1 and 1 at R@5, so it stays off.
- Extraction quality is still not validated: the human gold sheet (`docs/extraction_gold_sheet.csv`) is prepared and empty. 19 of 148 documents still have no content concept (vocabulary gap). Rules, results and the handoff for Person A: `docs/E13_kg_fixes2.md`; requests to her: `docs/requests_for_PersonA.md`.

---

## Addendum 2026-11-14 (KG fixes 3, branch `person-b/kg-fixes3`)

- Stage 4 (candidates): the Gap 5 vocabulary overlay (`knowledge_graph/vocabulary_extension.json`, proposed and pending ontology-owner approval; the shared `ontology/` is untouched) adds 6 `Concept` nodes with `source="vocabulary_extension"` and raises `MENTIONS_CONCEPT` edges from 7 to 49. Documents with a content concept: 129 -> 144; 4 remain uncovered (FAQ_C11_021, FAQ_C11_022, FAQ_C23_045, INC_C04_INC_2026_0163). `graph.json` is 345 nodes / 1739 edges.
- The edge type is not a bridge of `graph_expand`: on the 52 dev questions 0 top-5 lists changed, 0 losses, incident pairs 3/5 vs 3/5.
- Extraction quality is still not validated (gold sheet unfilled); `Account Closure & Deactivation` visibly matches other senses of "deactivate". Rule, per-concept table and handoff: `docs/E13_kg_fixes3.md`.

---

## Addendum 2026-11-14 (KG fixes 4, branch `person-b/kg-fixes4`)

- Precision pass on the vocabulary overlay: the bare `deactivate`/`deactivated` (Account Closure & Deactivation) are replaced by three specific phrases, `Airplane Mode` is removed, and 7 wrong-sense matches out of 80 are gone (0 of 71 after; 1 unsure left unchanged). Connectivity Troubleshooting now links one document and is dropped by the rule, so `graph.json` has 5 overlay Concept nodes, 40 `MENTIONS_CONCEPT` edges, 344 nodes / 1730 edges.
- Documents with a content concept: 129 before the overlay, 144 after KG fixes 3, 143 now (FAQ_C29_058 uncovered); 5 uncovered in all. Dev sets: top 5 identical for all 52 questions. Judgements are one reader's; extraction quality is still unvalidated (gold sheet unfilled). Details: `docs/E13_kg_fixes4.md`, table `docs/E13_kg_fixes4_judgements.csv`.

---

## Addendum 2026-11-14 (KG fixes 5, branch `person-b/kg-fixes5`): extraction check on the AI-labelled sheet

- The 20-document gold sheet is now labelled **by an AI assistant (two passes), NOT by a human; human review of five borderline rows (EML_008, INC_C25_INC_2026_0179, SOP_C25_FTTH_FAULT_HANDLING, TRN_004, INC_C08_INC_2026_0211) is pending.** Status: AI-labelled, human review pending - not validated. The blank template `docs/extraction_gold_sheet.csv` is unchanged; the labelled copy is `docs/extraction_gold_sheet_reviewed.csv`. Method, causes and caveats: `docs/E13_extraction_validation.md`.
- Five content labels pooled (Service, Channel, VerificationMethod, Requirement, Location), 52 predictions: **strict precision 0.519, recall 0.931 (tp 27, fp 25, fn 2); lenient precision 0.942, recall 0.961** (the 22 template-sentence or weak-mention predictions counted as correct). The current extractor and the sheet's own (pre-overlay) predictions score the same on these labels. The Concept label is reported separately and is not comparable.
- **Main finding: a large part of the extractor's edges comes from template text.** 25 of 52 predictions (48