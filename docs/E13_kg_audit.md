# E13 knowledge-graph audit (read-only)

Audited: branch `person-b/kg-hardening` at `4956b37d9f8ea76f095de168280ca8e51e5717c1` (this report is the only change, on branch `person-b/kg-audit`).
No code, constant, data or frozen file was changed. Measurements used scratch scripts outside the repository (not committed); graph builds went to a
temporary directory, failure tests ran in throw-away clones under the session scratchpad. Interpreters: `rag-api` conda env (models cached locally).

**Short version.**
1. The graph itself is sound and reproducible (148/148 documents, byte-identical rebuild, no orphans, no category or related-id disagreement with the corpus).
2. In retrieval the graph is ON but almost **inert**: of 597 graph/link documents appended to the pool over the 52 dev questions, **1 reached the final top 5**;
   19 were in the CrossEncoder's own top 5 and were pushed out by the `rrf_blend` arithmetic (Part B).
3. The pipeline **crashes without `graph.json` even with the graph switched off**, and also without models, FAISS index, a valid graph file, or (when a
   customer id is passed) the structured DB; only a CrossEncoder failure degrades gracefully (Part C). In a fresh clone 7 end-to-end tests fail for this reason.
4. The structured side is **NOT CONNECTED** to the graph that retrieval uses; the connection exists only as concept *names* (gate hint, a `concept` label on facts that
   the answer layer then drops) and as an offline `concept_layer.json` that nothing reads (Part D).
5. Tag bridges quietly re-introduce category expansion (104/148 documents carry a `cNN` tag identical to their own category), which the design says is excluded.

---

## 0. Plan vs reality (original plan: ontology, knowledge graph, query enrichment, router, grounded answers)

Compared against `docs/E13_architecture_status.md` and the roadmap target architecture (`docs/E13_Hybrid_Fusion_Roadmap.md` Section 2).

| Item | Status | File and evidence |
|---|---|---|
| Shared telecom ontology (entities, relationships, categories) | **DONE** | `ontology/ontology_schema.json`, `entity_definitions.json`, `relationship_definitions.json`, `ONTOLOGY_DESIGN.md`; crosswalk 28 structured tables -> 23 concepts, but only **8 of 28** structured C-codes agree with the document C-codes (`concept_layer.json`/crosswalk) |
| Document knowledge graph build | **DONE** | `knowledge_graph/graph_builder.py`; fresh build 337 nodes / 1,636 edges, sha256 identical to the existing `output/graph.json` (A0) |
| Content layer (services/channels/verification/requirements/locations) | **PARTIAL** | `content_extractor.py`; 23 of 148 documents have **no** content-concept edge (A3); extraction validation is provisional, gold template unfilled (`extraction_validation.json`: `template_filled: false`) |
| Document-to-document links (`RELATED_TO`) | **PARTIAL** | `build_related_aliases.py`; 47 of 84 resolve, 37 do not; 75 of 148 documents touch no resolved link (A4) |
| Structured KG from 28 SQL tables | **DONE as an artifact, NOT wired** | `structured_graph_builder.py`, `output/structured_graph.json`; no retrieval code reads it (by decision: "do not wire the structured Neo4j KG into retrieval") |
| Concept bridge (structured table <-> document category/service) | **PARTIAL** | `concept_bridge.py` -> `output/concept_layer.json` (23 concepts, 28 REALIZES, 33 EXPRESSES); read only by `evaluate_unified_graph.py`; Neo4j load never executed (`KG_REPORT.md` 5.10); `graph.json` has no `Concept`/`EntityType` nodes (D) |
| Query understanding (intent, personal/policy, concept hint) | **DONE** | `hybrid/clauses.py`, `query_gate.py`, `textmatch.py` |
| Query *enrichment* (rewrite/expand the query with concepts/synonyms) | **MISSING in this branch** | no query rewriting anywhere in `hybrid/`; Person A's `normalise_query` exists only on `origin/integrate/kg-ontology-router-ui` (`integration/rag/semantic_layer.py`), not merged here |
| Router (structured / unstructured / both, identity and privacy guards) | **DONE** | `hybrid/router.py`; frozen benchmark leakage 0 in every run |
| Candidate generators: FAISS | **DONE** | `hybrid/retrievers.py:49` (`VectorRetriever`, 248 documents incl. 100 SciFact) |
| Candidate generators: metadata-aware filtering/boosting, ColPali | **MISSING in the hybrid pipeline** | `hybrid/retrievers.py` uses only `VectorRetriever`; Person A's metadata/ColPali retrievers are not called |
| Candidate generator: document graph (concept expansion + links) | **DONE, low reach** | `knowledge_graph/graph_augmented_retrieval.py:167`, `hybrid/retrievers.py:63`; see Part B |
| Candidate fusion | **DONE** | `hybrid/fusion.py` append-only (the old bonus merge was a bug; fixed at `13b154d`) |
| Ontology/entity/relationship signals as a scoring signal | **MISSING (changed by decision)** | graph is now a source, never a ranker (`docs/E13_graph_fusion_fix.md`) |
| Controlled CrossEncoder rerank | **DONE** | `hybrid/rerank.py` (pool cap 20, default `rrf_blend` w=1.0) |
| Dedup + context selection | **DONE** | `hybrid/dedup.py`, `context.py`, `snippets.py` |
| RAG LLM | **PARTIAL (off by default)** | `hybrid/answer.py::LLMAnswerer` behind a verifier, no model configured |
| Grounded answer + citations + verifier | **DONE** | `hybrid/answer.py`, `groundedness.py` (R1-R6, 30/30 mutants flagged) |
| Graceful degradation when an asset is missing | **PARTIAL** | only CrossEncoder failure falls back (C) |

---

## A. Build and content

### A0 Build check
```
fresh build (temp dir) vs existing knowledge_graph/output/graph.json: identical = True  7d56dac7e787  7d56dac7e787
documents loaded: 148 | graph nodes 337 edges 1636
```
`knowledge_graph/output/` is **not tracked by git** (0 tracked files): a fresh clone has no graph until `python -m knowledge_graph.graph_builder` is run.

### A1 Counts by type
Nodes (337): Document 177 (148 canonical + **29 stub**), Tag 68, Category 30 (C01-C29 + `GENERAL`), Department 13, DocumentType 13, Service 14,
Channel 5, VerificationMethod 5, Requirement 4, CustomerScope 4, Location 2, Dataset 1, SourceAuthority 1.

Edges (1,636): APPLIES_TO_SCOPE 148, AUTHORED_BY 148, BELONGS_TO_CATEGORY 148, IS_TYPE 148, OWNED_BY_DEPARTMENT 148, PART_OF_DATASET 148, HAS_TAG 208,
MENTIONS_SERVICE 192, MENTIONS_CHANNEL 89, MENTIONS_VERIFICATION 73, MENTIONS_REQUIREMENT 15, MENTIONS_LOCATION 9, RELATED_TO 84, AVAILABLE_VIA 35,
REQUIRES_VERIFICATION 31, REQUIRES_DOCUMENT 12.

### A2 Orphans, stubs, corpus agreement
- Orphan nodes (no edges): **0**. Stub Document nodes: **29** (the distinct unresolved `related_ids` targets).
- Canonical documents in the graph = the 148 corpus documents (same set). Category mismatches: 0. Documents whose `related_ids` count differs from RELATED_TO edges: 0.
- Every graph document has a chunk in the FAISS index. The index also holds 100 `SCIFACT_*` public documents that are not in the graph (no dev question retrieves one in its top 5).

### A3 Documents with no concept
23 of 148 have **no** content-concept edge (FAQ 17, INC 3, MAN 2, EML 1); 3 of them also have no tag:
`EML_005, FAQ_C04_008, FAQ_C08_015, FAQ_C09_017, FAQ_C09_018, FAQ_C11_021, FAQ_C11_022, FAQ_C12_023, FAQ_C12_024, FAQ_C19_037, FAQ_C19_038, FAQ_C21_041,
FAQ_C21_042, FAQ_C23_045, FAQ_C24_047, FAQ_C24_048, FAQ_C29_057, FAQ_C29_058, INC_C04_INC_2026_0163, INC_C08_INC_2026_0142, INC_C18_INC_2026_0197,
MAN_DEVICE_VOLTE_001, MAN_IOT_PORTAL_001`.
Distribution: 27 documents have exactly 1 concept, 31 have 2; mean 2.6, median 2, max 11. 53 documents have only hub content concepts (tags ignored).

### A4 `RELATED_TO`: 84 total, 47 resolved, **37 unresolved** (29 distinct targets)
Unresolved, by cause:
- **21 `KB_Cnn_* -> FAQ_Cnn_001`** (FAQ target ambiguous: two FAQs per category, deliberately never aliased): C02, C03, C04, C05, C06, C07, C08, C09, C13, C16, C17, C18, C19,
  C20, C21, C22, C23, C25, C26, C28, C29.
- **16 `FAQ_Cnn_* -> KB_Cnn_overview`** in categories that have **no KB document**: C01, C10, C11, C12, C14, C15, C24, C27 (two FAQs each).
Full list (source -> original target): `FAQ_C01_001/002 -> KB_C01_overview`; `FAQ_C10_019/020 -> KB_C10_overview`; `FAQ_C11_021/022 -> KB_C11_overview`;
`FAQ_C12_023/024 -> KB_C12_overview`; `FAQ_C14_027/028 -> KB_C14_overview`; `FAQ_C15_029/030 -> KB_C15_overview`; `FAQ_C24_047/048 -> KB_C24_overview`;
`FAQ_C27_053/054 -> KB_C27_overview`; and the 21 KB sources above -> `FAQ_Cnn_001`. Audit file: `knowledge_graph/related_id_alias_audit.csv`.

The 47 resolved links form 47 undirected pairs touching **73 of 148** documents.

### A5 Hub concepts (df > 10% of 148 documents, i.e. >= 15)
| concept | documents | share |
|---|---|---|
| VerificationMethod: OTP | 47 | 32% |
| Service: Complaint Registration | 45 | 30% |
| Channel: My NovaTel App | 38 | 26% |
| Channel: Self-Care Portal | 33 | 22% |
| Service: KYC Verification | 30 | 20% |
| Tag: how-to | 21 | 14% |
| Service: Refund | 19 | 13% |
| Service: Recharge | 17 | 11% |
| Service: SIM Swap | 15 | 10% |
| Service: Mobile Number Update | 15 | 10% |

### A6 Duplicate / near-duplicate concepts
Same name under two labels: **`recharge`** (Service `Recharge` and Tag `recharge`), **`aadhaar`** (Requirement and VerificationMethod). No other normalised or substring duplicates.
Odd tags: 29 category-code tags `c01`..`c29` (see B6), generic tags `new`, `number`, `p1`, `p2`, `rca`.

### A7 Category coverage C01-C29
No category is empty; all 148 documents have a category; 7 documents sit in `GENERAL` (not a C01-C29 code, no structured counterpart).

| Category | docs | with concepts | docs in a resolved link | note |
|---|---|---|---|---|
| C11 International Calling & ISD | 2 | **0** | 0 | no concepts, no links |
| C12 Device Compatibility | 3 | **0** | 0 | no concepts, no links |
| C24 IoT & M2M Services | 3 | **0** | 0 | no concepts, no links |
| C29 Technical Support & Troubleshooting | 3 | 1 | 3 | |
| C19 Privacy | 4 | 2 | 3 | |
| C21 Termination | 6 | 3 | 3 | |
| C01, C10, C14, C15, C27, GENERAL | 2,3,3,2,2,7 | all | **0** | concepts present, no resolved link |
| remaining 19 categories | 2-9 | most | >= 3 | |

### A8 Disagreements graph.json vs the 148-document corpus
None found: same document set, same categories, same related-id counts. Documentation drift: `KG_REPORT.md` still headlines **363 nodes** (the alias repair removed 26 stub
nodes; actual 337; edges unchanged at 1,636); only section 5.1 carries a dated addendum.

---

## B. Retrieval use

### B0 How `graph_expand` picks seeds and bridges (`knowledge_graph/graph_augmented_retrieval.py:167`)
Seeds: the **top `GRAPH_SEEDS = 5` documents** of the vector result (`VECTOR_DEPTH = 10` chunks -> 7-10 document-level hits). Bridges: `DEFAULT_BRIDGES = (Service, Channel, VerificationMethod, Tag)`,
hubs included; `Category` is excluded by design. Each shared concept adds `1/(1+seed_rank)`; top `GRAPH_CANDIDATES = 20` kept. Seeds are healthy: of 260 seeds (5 x 52 questions)
none is outside the graph, 6 have zero bridge concepts, 8 have only hubs, 246 have at least one specific concept.

### B1 Settings read and ignored by `hybrid/pipeline.py`
Read: `GRAPH_ENABLED` (True, line 21), `LINKS_ENABLED` (True, line 24), `LINK_WEIGHT` (0.15, only as an on/off switch), `max_pool` (20), `top_k`, rerank `mode`/`blend_weight` (default `rrf_blend`, 1.0), and the **gate's graph weight**
(`query_gate.py:200-211`) - which after the append-only fix is only an on/off for the concept list.
**Ignored / dead:** the `graph_expand` hardening parameters (`hub_fraction`, `specificity`, `max_documents`, `allowed_labels`) - `pipeline.py` never passes `graph_kwargs`, so the live path is the legacy profile;
the 0.5 vs 0.15 difference of the gate (identical behaviour); `fusion.VECTOR_WEIGHT` (unused); `k` only feeds `fusion_score`.

### B2 Do the graph features work after the append-only fix?
Yes mechanically: vector order is untouched, graph/link documents are appended, links join regardless of the gate, caps hold (`test_graph_append_only.py` 8, `test_links.py` 11 pass).
Two design inconsistencies remain:
- **Two link mechanisms overlap.** `build_candidates(use_related_links=True)` (`retrievers.py:63,95`) puts RELATED_TO neighbours of the top-5 seeds FIRST in the **graph** list (gate-dependent), and
  `link_candidates_for` adds a separate list (top-3 seeds, cap 2). Over the dev set: 80 linked documents via the graph list, 43 via the link list, 43 identical. With gate weight 0.0 (17 of 52 questions)
  only the 2-document link list survives.
- The hardened graph profile selected earlier (`V2 h=0.05 m=3`) is not used anywhere in the live path.

### B3 Measurement on the 52 dev questions (main 29, mini 9, validation 14), live defaults
```
pipeline defaults: GRAPH_ENABLED=True LINKS_ENABLED=True LINK_WEIGHT=0.15
questions: 52 | gate weight > 0: 35, == 0: 17 | vector documents per question min 7 max 10 | fused candidates (before pool cap) min 7 max 32 mean 20.4
(a) PROPOSED   graph-list docs not already vector hits: 895, in all 52 questions | link-list docs: 43, in 32 questions
    entered fusion after the gate: graph-list 597 (49 questions) | links 43 (32 questions)    [43 of the 597 are also link docs]
(b) INSIDE the 20-pool: graph-list 400 (49 q) | links 43 (32 q)         => 7.7 appended documents per question compete in the pool
    CUT by the pool cap (entered fusion, position > 20): 197 docs in 33 questions
(c) REACH the final top 5: graph-list 1 (1 q) | links 1 (1 q)  [the same document, INC_C18_INC_2026_0197, mini-9 question on fraud with financial loss]
    questions where graph/link docs entered fusion but none reached the top 5: 48 of 49
    questions where ALL entered graph/link docs were cut by the cap (unreachable): 0
per set (graph proposed/entered/pool/top5): main29 490/318/212/0 | mini9 157/119/80/1 | validation14 248/160/108/0
composition of the appended documents: concept-only 855 proposed | top-5-seed links 80 | link list 43 (all 43 also in the 80)
```
**Verdict on the pool cap.** The cap of 20 does not make graph documents unreachable in any question (0 questions where all are cut), but it cuts 197 of 597 (33%) entered documents in 33 questions, and what remains competes
with 7-10 vector documents. In practice the **blend, not the cap, is the barrier**:

```
appended documents in the pool by origin | in CrossEncoder-only top 5 | in final top 5 | CrossEncoder top 5 but pushed out by the blend
concept   336 | 15 | 0 | 15        link (top-3 seeds) 43 | 3 | 1 | 2        link (top-5 seeds, in graph list) 21 | 2 | 0 | 2
blend (rrf_blend, w=1): score = 1/(60+fusion_position) + 1/(60+rerank_rank)
appended doc at fusion position 11, CrossEncoder rank 1: 0.03048  vs  vector doc at fusion rank 5, rerank rank 5: 0.03077  (the vector doc wins)
appended doc at position 6: 0.03154 (can win) ... position 15: 0.02973 | position 20: 0.02889  (cannot beat a mid-ranked vector doc)
fusion position of appended documents in the pool: min 8, median 15
```
So an appended document can only enter the top 5 if it sits at fusion position <= ~10 AND the CrossEncoder ranks it near the top.

**Gold reachability.** 14 expected documents are not vector hits (reachable only via graph/links); 8 were proposed, 7 were inside the pool, **0 reached the top 5** (final ranks 7, 9, 9, 11, 11, 12, 13); only 2 of 52
questions have no expected document in the final top 5, so this did not cost recall on these sets, but it is the part of the graph's value that is structurally unavailable.

**Trace** (main 29, "I put my SIM into another phone and now it says there is no network"; expected `FAQ_C05_009` and `KB_C05_sim_swap_troubleshooting`):
```
vector (8): FAQ_C05_009, MAN_ESIM_001, FAQ_C29_057, MAN_DEVICE_VOLTE_001, SOP_C05_SIM_REPLACEMENT, FAQ_C12_024, TRX_002, SOP_C22_ACTIVATION_DELAY
fusion order (24, graph/links appended after position 8): ... KB_C05_sim_swap_troubleshooting (pos 9), KB_C29_network_reset_guide, FAQ_C05_010, SOP_C18_FRAUD_RESPONSE, ... ; cut by the pool: KB_C18_fraud_response, TRN_003, SOP_C17_KYC_VERIFICATION, TRN_004
final (fusion rank / rerank-only rank / final): FAQ_C05_010 11 / 4 / 8   (CrossEncoder's 4th, blended to 8th)   KB_C05_sim_swap_troubleshooting 9 / 7 / 9 (second expected document, rank 9)
16 of the 24 candidates are graph/link documents; none is in the final top 5
```

### B4 Category back door through tags
`graph_augmented_retrieval.py:19-22` says category expansion is deliberately excluded (the benchmark has one question per category). But **104 of 148 documents carry a `cNN` tag, and on all 104 it equals the document's own category**; `Tag` is a default bridge.
Over the 52 dev questions, 134 of 927 candidates (14%) share a category-code tag with the seeds (5 share *only* that). Not catastrophic, but it reintroduces the leak the design excluded.

### B5 Reproducibility drift
`hybrid/evaluate_hybrid.py` re-run now (to a scratch file): vector-only and blanket-graph rows identical to Phase 5; the E13 rows differ - main fusion-only R@1 0.6207 -> **0.7586**, mini hybrid R@1 0.2222 -> **0.4444**, mini hybrid MRR@5 0.4759 -> 0.6148 -
because the fusion semantics changed. `docs/E13_architecture_status.md` stage 4 still says "Phase 5 metrics reproduced exactly after the refactor" (true when written). The hardening and link-decoupling scripts likewise measure a system that no longer exists.

---

## C. Failure behaviour (throw-away clone of `4956b37`, plus mocks; nothing in the audited repo was changed)

| Scenario | Result |
|---|---|
| no `graph.json` (fresh clone, graph not built), defaults | **CRASH** `FileNotFoundError ... Build the graph first: python -m knowledge_graph.graph_builder` at `graph_augmented_retrieval.py:103 <- retrievers.py:50 (load_context)` |
| same, with `graph_enabled=False, links_enabled=False` | **CRASH, same error** - the graph index is loaded unconditionally by `load_context()` |
| `answer_question` without `graph.json` | **CRASH** (propagates; no catch in `answer.py`) |
| no models (empty HF cache, offline) | **CRASH** `OSError ... couldn't connect to huggingface.co` while building `VectorRetriever` (`retrievers.py:49`) |
| FAISS index missing | **CRASH** `RuntimeError ... could not open data\vectorstore\faiss.index` (`retrievers.py:49`) |
| `graph.json` corrupt | **CRASH** `JSONDecodeError` (`load_graph_index`) |
| structured DB missing, **customer id passed** (any question, even a pure policy one) | **CRASH** `OperationalError: unable to open database file` at `structured_adapter.py:65 <- router.py:125` (`lookup_msisdn` runs in `route_query`) |
| structured DB missing, no customer id | OK (documents returned; personal question -> `needs_identity`) |
| CrossEncoder cannot load (mocked) | **graceful**: loud warning, `rerank_status: FALLBACK: OSError ...`, input order returned, trace records it |
| empty graph list (mocked `graph_expand`/`related_neighbours` -> []) | OK, trace `graph enabled`, no linked documents |
| unknown concept / question with no concept | OK (gate weight 0.0, only the link list may enter); `graph_expand(["NO_SUCH_DOC"])` and `related_neighbours(...)` -> `[]` |

**Required behaviour not met:** `run_hybrid_query` does **not** fall back with a clear trace note when the graph (or any asset except the CrossEncoder) is missing - it raises.
Crash paths: missing/corrupt `graph.json` (even with the graph off), missing embedding model, missing FAISS index, missing structured DB whenever a customer id is passed.
The `FileNotFoundError` text is clear and names the fix command, but nothing catches it.

---

## D. Structured side: CONNECTED or NOT?

**NOT CONNECTED** in the graph and in retrieval. Where the two sides touch:

1. **By concept name only, in the gate.** `hybrid/query_gate.py:40-47,104` imports the concept vocabulary/service mapping from `knowledge_graph/concept_bridge.py`; the question's `concept_hint` becomes an on/off for the concept list (`query_gate.py:200-211`) and a trace field. It selects no documents and no tables.
2. **A label on structured facts.** `hybrid/structured_adapter.py:59,103` stamps `metadata["concept"]` (table -> concept via the crosswalk). `hybrid/context.py:34` then lists `concept` in `_FACT_BOOKKEEPING`, i.e. removes it from the fields, and `answer.py` never uses it. Dead end.
3. **Offline only.** `output/concept_layer.json` (23 concepts, 28 REALIZES_CONCEPT, 33 EXPRESSES_CONCEPT; 22 concepts bridge both sides; unmapped document services: DND Activation, Loyalty Redemption, Refund; `Retail & Store Network` has no document side) is read only by `evaluate_unified_graph.py`. `graph.json` contains only the 13 document-side labels - no `Concept`, no `EntityType`. The Neo4j loaders were never executed (`KG_REPORT.md` 5.10).
4. **Category tags are carried, never joined.** `structured/schema.py` has 31 `category_tag` occurrences; the adapter passes `category` through (`structured_adapter.py:113`); `hybrid/tests/test_structured_adapter.py:204 TestNoCategoryJoin` fails if any hybrid module compares category codes. Correct, because only 8 of 28 structured codes agree with the document codes (structured `C11` = tickets, document `C16` = Complaints).
5. **Common Result Schema:** structured results (`source: structured_sql`) and document results (`source: unstructured`) share the field set, but `category` means a different taxonomy on each side, so it is not a join key.
6. The router sends a question to the structured source by **keyword intent** (`router.py` INTENT_TERMS), not through the ontology.

### Smallest connection WITHOUT adding row data (proposal; not implemented)
**Concept metadata in `graph.json`.** Emit 23 `Concept` nodes and the 33 existing `EXPRESSES_CONCEPT` edges (Category/Service -> Concept) from `concept_layer.json` into the graph build, each Concept carrying a `tables` property (names of the realizing structured tables; metadata, no rows), and put the table names on the `Category` nodes that express the concept.
Join on the **concept name, never the C-code**. Resulting groups are small: 22 concepts bridge both sides; concept -> documents via category = 2-9 documents (largest 9), e.g. Billing & Invoices -> C04 -> 7 documents -> `invoices`; Complaints & Grievances -> C16 -> 6 documents -> `tickets`, `escalation_cases`.
Uses (each optional, in increasing risk): (i) stop dropping `concept` in `context.py` and let the answer layer say which tables a retrieved document's concept relates to (read-only hint, zero accuracy risk); (ii) when the gate resolves a concept, append that concept's category documents as a graph candidate source (must be pre-declared and measured like the other graph changes).
- Cost: build change ~60-80 lines in `graph_builder.py`/`concept_bridge.py` + ~30 lines in `GraphIndex` + ~15 tests, about 0.5-1 day; use (ii) another ~0.5 day plus a dev-set experiment.
- Risk: no data risk (metadata only). `graph.json` gains node labels - Person A's reader (`_read_related_edges`: nodes -> key map, `RELATED_TO` edges) ignores them. Accuracy risk only for use (ii), and the concept groups are small (no new hubs). C-code confusion is avoided by joining on names; 6 of the 23 concepts form three pairs that share one category (`Plan Catalogue`/`Subscription` C02, `Payments`/`Recharge` C03, `Network Coverage`/`Network Outages` C08), so use (ii) would fetch the same documents for both concepts - harmless but should be deduplicated.
- Smaller alternative (no graph change, ~0.25 day): a generated static map concept -> {categories, documents, tables} consumed only by `context.py`/`answer.py` for hint (i). No retrieval effect.

---

## E. Tests

| File | Tests | Covers |
|---|---|---|
| `knowledge_graph/tests/test_graph_expand.py` | 14 | golden legacy output (11 recorded cases), hub cut, specificity, caps, label restriction, determinism, `related_neighbours` incl. both directions for the 5 incident pairs |
| `knowledge_graph/tests/test_related_aliases.py` | 13 | alias rules, 47/37 counts, FAQ never aliased, byte-identical builds, Person A reader compatibility (47 pairs) |
| `hybrid/tests/test_graph_append_only.py` | 8 | append-only fusion contract (order, no boost, links first, weights are switches, regression arithmetic) |
| `hybrid/tests/test_links.py` | 11 | link list (top-3 seeds, cap 2, gate 0), pipeline switch |
| `hybrid/tests/test_graph_default.py` | 4 | `GRAPH_ENABLED` default, opt-out, trace |
| `hybrid/tests/test_fusion.py` | 10 | document-level keying, worked arithmetic |
| `hybrid/tests/test_setup_check.py` | 5 | missing-graph error text, `setup_check` |
| `structured/tests/test_fk_follow.py`, `test_customer_scoping.py` | 8 + 11 | structured side (not graph, listed for completeness) |
Whole suite on the audited head: 320 passed, 1 skipped.

**Skipped:** the KYC acceptance test (FAQ_C17_034 is not retrieved for that question) - a standing skip. **Conditional skips:** without `graph.json` 15 graph tests skip with a clear message (14 in `test_graph_expand.py` + 1 alias-compat) and `test_links.py` skips as a whole module (11; counted as 1 collection skip).
**Fresh clone with no `graph.json`: `7 failed, 288 passed, 16 skipped`.** The failing tests are the end-to-end ones that gate only on faiss/sentence-transformers and then call `run_hybrid_query`/`answer_question`:
`test_phase8_fixes::TestPipelineFlags::test_flag_reaches_blocked_and_trace_while_documents_still_run`, `test_phase8d::TestDocumentsSurviveMissingIdentity::test_structured_route_without_customer_still_returns_generic_documents`,
`test_phase9d2::TestKycAcceptanceRealData` (2), `test_router::TestPipeline` (3) - all `FileNotFoundError: ... graph.json`.
**Flaky:** none seen - the 73 graph-related tests passed 3 of 3 repeats (1.4-1.5 s each); results are deterministic by construction (sorted keys, no randomness).

**Untested:** the content layer (tests build the metadata-only graph; `content_extractor.py` has no test); `concept_bridge.py` (only through the gate's imports); `graph_loader.py`/Neo4j (never executed); `graph_queries.py`, `unified_queries.py`, all `structured_*` graph modules, `validate_extraction.py`, `visualize_graph.py`; the real (unmocked) `build_candidates` path is exercised only by the model-dependent end-to-end tests and the evaluation scripts; no test for a missing/corrupt graph in `run_hybrid_query` (the behaviour is a crash, see C); no test that the pool cap or the blend leaves room for appended documents.

---

## F. Ranked bug and gap list (nothing fixed)

Severity: **A** accuracy impact, **C** correctness, **K** cosmetic. Plan: yes / no / optional.

### In the architecture plan
| # | Sev | Finding | Evidence | Plan | Proposed fix | Size |
|---|---|---|---|---|---|---|
| 1 | A | Graph/link documents are almost inert under `rrf_blend`: 1 of 597 appended docs reaches the top 5; 19 CrossEncoder-top-5 appended docs are pushed to ranks 6-11 (B3); costs ~7.7 extra CrossEncoder pairs per question for no benefit | `rerank.py:64`, B3 numbers and trace | yes (graph as signal/source) | pre-declared experiment: give appended documents a fair blend (e.g. compute `rank_fusion` among appended documents only, or protect-slot V3 variant under the new fusion, or override mode for them); measure on dev sets | S (~20 lines) + experiment |
| 2 | C | `run_hybrid_query` crashes without `graph.json` even with the graph off; also on missing models, FAISS, corrupt graph, or (with a customer id) a missing structured DB (C) | `retrievers.py:50`, `router.py:125`, `structured_adapter.py:65` | yes (graceful degradation is assumed by the status doc: "graph disabled by config") | load the graph lazily and only when enabled; catch and trace `graph unavailable: <reason>`; guard `lookup_msisdn`; keep the clear error text | S-M (~40 lines + 6 tests) |
| 3 | C | 7 end-to-end tests fail in a fresh clone without a built graph | C/E | yes | skip them on missing `graph.json` (same helper as the KG tests) | XS |
| 4 | A | Structured side not connected to the graph that retrieval uses; `concept` label is dropped by `context.py:34`; `concept_layer.json` unused; Neo4j never run | D | yes (ontology mapping / unified graph box) | smallest connection in D (concept metadata in `graph.json`, stop dropping `concept`) | M (0.5-1 day) |
| 5 | A | 23 of 148 documents have no concept (all of C11, C12, C24; 17 FAQs); 3 documents have neither concept nor tag | A3, A7 | yes (known: KG_REPORT 5.3) | extend `content_extractor` rules to FAQ answer text; re-measure coverage | M |
| 6 | A | 37 of 84 `RELATED_TO` unresolved; 75 documents (51%) touch no link; 9 categories have no resolved link | A4, A7 | yes (known limitation 5.1) | needs corrected `related_ids` in the source documents (Person A) or an explicit mapping decision for FAQ_Cnn_001; not deterministic from the corpus | S (data owner) |
| 7 | A | Extraction quality unvalidated: gold template not filled, 14 predictions flagged, 38 of 67 auto-verifiable | `extraction_validation.json` | yes (validation planned) | fill the 20-document gold sample (human), re-run `validate_extraction` | S (hours, human) |
| 8 | A | Query enrichment missing in this branch (exists only on `integrate/kg-ontology-router-ui`); metadata-aware boost and ColPali not in the hybrid pipeline | 0 | yes (roadmap target boxes) | merge/port Person A's `normalise_query`; decide on ColPali/metadata candidates | M-L |
| 9 | C | Two overlapping link mechanisms (graph-list links from top-5 seeds, gate-dependent, plus the 2-document link list); behaviour differs at gate weight 0 | B2 | no (accidental) | call `build_candidates(use_related_links=False)` from `run_hybrid_query`, keep the link list only | XS |
| 10 | K | Stale documentation: `KG_REPORT.md` headline 363 nodes (actual 337); `docs/kg_hardening_for_personA.md` and the status doc still describe the graph/links as OFF in body text (correction banners exist); stage-4 "Phase 5 metrics reproduced exactly" no longer true (B5) | A8, B5 | yes | add dated addenda / re-state the numbers | XS |

### Optional (not in the plan)
| # | Sev | Finding | Evidence | Proposed fix | Size |
|---|---|---|---|---|---|
| 11 | A | `cNN` tags re-introduce category expansion via the Tag bridge (104/148 docs; 14% of candidates share one) against the stated design | B4 | exclude tags matching `^c\d\d$` from the bridge labels (or drop them at build) | XS + measure |
| 12 | A | The live path uses the legacy `graph_expand` (hub bridges, no cut): 72% of candidates share only hubs (hardening audit), 855 concept documents proposed for 52 questions, 33% cut by the cap, 16 of 24 pool slots in the example trace; pool noise and rerank cost with no gain | B1, B3 | pass the hardened profile via `graph_kwargs` in the pipeline (a measured choice, after fix 1) | XS + experiment |
| 13 | K | Dead settings: hardening parameters, gate tiers 0.5/0.15, `VECTOR_WEIGHT`, `link_weight` magnitude | B1 | delete or document as switches | XS |
| 14 | K | Duplicate concepts `recharge` (Service/Tag) and `aadhaar` (Requirement/VerificationMethod); generic tags `new`, `number`, `p1`, `p2`, `rca` | A6 | normalise at build | XS |
| 15 | K | `GENERAL` category (7 documents) has no ontology/structured code and no resolved link | A7 | decide: map to a concept or leave | XS |
| 16 | A | Test gaps: content layer, `concept_bridge`, Neo4j loaders, graph queries, real `build_candidates`, missing-graph behaviour | E | add tests as the matching code is changed (esp. with fix 2) | S-M |
| 17 | K | `knowledge_graph/output/` untracked: every clone must rebuild, Person A's reader needs it | A0 | document (done in README) or track the single `graph.json` | XS |

### Could not check
- Neo4j load and queries (no server; never executed per `KG_REPORT.md` 5.10) and the structured KG modules' correctness beyond their existence.
- Person A's 42-question harness and the runtime of `integration/rag/semantic_layer.py` (only its `_read_related_edges` function was read from `origin/integrate/kg-ontology-router-ui`).
- The LLM answer path, ColPali, and any quality judgement on the answer text.
- The blend-pushed-out documents were measured on 52 dev questions with gold labels for only part of the corpus; whether a fairer blend would help is **not shown** here.
