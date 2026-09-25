# NovaTel Knowledge Graph — Full Report

**Author:** Person B (ontology + knowledge graph layer)
**Scope:** everything under `ontology/` and `knowledge_graph/`, built on top of Person A's
unstructured ingestion pipeline. `ingestion/`, `data/`, `structured/` and
`data/vectorstore/` are read-only inputs; nothing in them was modified.

**Corpus:** the 148 canonical documents in `data/processed/documents/*.json`.

> **Post-merge notice (2026-09-26).** Person A's `person-a/unstructured-integration` branch
> was merged into `main`, rewriting the `content` field of all 148 documents (average length
> 643 → 2,066 characters, adding structured "Short Answer / Detailed Explanation / Key
> Details / Conditions / Escalation / Example Scenario" sections) while leaving every
> metadata field byte-identical. Phase 1 (metadata graph) is unaffected — 333 nodes / 1,180
> edges, unchanged. Phase 2 (content layer) is rebuilt against the new text; §2's Phase 2
> block and §5.3 are marked **pre-merge baseline, superseded** with the current numbers given
> alongside. §5.11 documents a false-positive bug the new text exposed and how it was fixed.

---

## 1. Ontology summary

Three layers of definition, all machine-readable:

| File | Contents |
|---|---|
| `ontology/ontology_schema.json` | 13 node labels, 16 relationship types, the id convention, the dangling-reference policy, the 30-code category catalog |
| `ontology/entity_definitions.json` | Per node type: description, source field, key field, properties |
| `ontology/relationship_definitions.json` | Per relationship: from/to labels, source field, meaning, confidence |
| `ontology/ONTOLOGY_DESIGN.md` | Prose design doc for both phases |

### Metadata layer (Phase 1) — 8 node labels, 8 relationships

Every node and edge is read verbatim from a declared metadata field. No inference.

| Node | Key | Source field | Count |
|---|---|---|---|
| `Document` | `document_id` | `document_id` | 148 (+55 stubs) |
| `DocumentType` | value | `document_type` | 13 |
| `Category` | code | `category` | 30 |
| `Department` | value | `department` | 13 |
| `CustomerScope` | value | `customer_scope` | 4 |
| `Tag` | tag string | `tags` | 68 |
| `SourceAuthority` | value | `source_authority` | 1 |
| `Dataset` | derived from id prefix | `document_id` | 1 |

Relationships (all Document → hub): `BELONGS_TO_CATEGORY`, `IS_TYPE`,
`OWNED_BY_DEPARTMENT`, `APPLIES_TO_SCOPE`, `HAS_TAG`, `AUTHORED_BY`,
`PART_OF_DATASET`, plus `RELATED_TO` (Document → Document).

### Content layer (Phase 2) — 5 node labels, 8 relationships

Extracted from `title` + `content` with a **curated pattern dictionary** — canonical
concept names mapped to explicit trigger phrases, matched case-insensitively on
non-alphanumeric boundaries. No spaCy, no model, no LLM. The dictionary lives in
`knowledge_graph/content_extractor.py` and is copied into every output file.

| Node | Declared | Evidenced |
|---|---|---|
| `Service` | 14 | 14 |
| `Channel` | 6 | 5 |
| `VerificationMethod` | 7 | 5 |
| `Requirement` | 5 | 4 |
| `Location` | 2 | 2 |

Relationships: `MENTIONS_SERVICE`, `MENTIONS_CHANNEL`, `MENTIONS_VERIFICATION`,
`MENTIONS_REQUIREMENT`, `MENTIONS_LOCATION` (Document → concept, `confidence=pattern_match`,
carrying `matched_terms` and an `evidence` snippet), plus three Service-anchored
co-occurrence relationships — `AVAILABLE_VIA`, `REQUIRES_VERIFICATION`,
`REQUIRES_DOCUMENT` — marked `confidence=cooccurrence` with a `support` count.

**Boundary-safe matching matters.** Three triggers were deliberately narrowed because the
naive form is wrong on this corpus: `port` would fire inside "self-care **port**al" (16
documents), `pan` inside "**Pan**-India" (every incident header), `store` on every
"visit a store".

**VerificationMethod vs Requirement** is decided by what the phrase describes: a
verification *act* (OTP, Video KYC, biometric) vs a *document the customer must produce*
(valid photo ID, address proof, passport). This is why FAQ_C01_001 yields
`Requirement: Valid Photo ID` and not `VerificationMethod: Photo ID`.

---

## 2. Graph statistics

### Phase 1 (metadata subgraph)

```
total_nodes: 333          total_edges: 1180
Document 148 | DocumentType 13 | Category 30 | Department 13
CustomerScope 4 | Tag 68 | SourceAuthority 1 | Dataset 1
StubDocument(unresolved) 55

BELONGS_TO_CATEGORY 148 | IS_TYPE 148 | OWNED_BY_DEPARTMENT 148
APPLIES_TO_SCOPE 148 | HAS_TAG 208 | AUTHORED_BY 148
PART_OF_DATASET 148 | RELATED_TO 84

average_degree 7.0871 | connected_components 1 | duplicate_node_rate 0.0
related_ids 84 total / 84 unresolved / unresolved_rate 1.0
```

`connected_components: 1` is **not** evidence of rich cross-linking. `SourceAuthority` and
`Dataset` are single-valued, so all 148 documents attach to the same two hubs, which alone
makes the graph connected. Real document-to-document connectivity is zero: every
`RELATED_TO` edge terminates on a stub.

### Phase 2 (full graph)

**PRE-MERGE BASELINE — SUPERSEDED.** Computed against the original ~643-char/document
corpus, before the Sep 2026 merge rewrote document content:

```
total_nodes: 363          total_edges: 1473
Service 14 | Channel 5 | VerificationMethod 5 | Requirement 4 | Location 2

MENTIONS_SERVICE 132 | MENTIONS_CHANNEL 48 | MENTIONS_VERIFICATION 37
MENTIONS_REQUIREMENT 18 | MENTIONS_LOCATION 8
AVAILABLE_VIA 28 | REQUIRES_VERIFICATION 16 | REQUIRES_DOCUMENT 6

documents_with_at_least_one_content_edge: 106 / 148
```

**CURRENT (post-merge, post-fix) — the live baseline.** Same 30 concept nodes (the
dictionary vocabulary didn't change), roughly 1.5× the mention edges — expected, since the
new document text is 3.2× longer and elaborates every answer instead of stating it once:

```
total_nodes: 363          total_edges: 1636
Service 14 | Channel 5 | VerificationMethod 5 | Requirement 4 | Location 2

MENTIONS_SERVICE 192 | MENTIONS_CHANNEL 89 | MENTIONS_VERIFICATION 73
MENTIONS_REQUIREMENT 15 | MENTIONS_LOCATION 9
AVAILABLE_VIA 35 | REQUIRES_VERIFICATION 31 | REQUIRES_DOCUMENT 12

documents_with_at_least_one_content_edge: 125 / 148
```

Full before/after, including the intermediate post-merge-pre-fix numbers (which briefly
peaked higher on `MENTIONS_SERVICE` before a false-positive trigger was fixed — see §5.11):

| Metric | Pre-merge (old) | Post-merge, pre-fix | Post-merge, post-fix (current) |
|---|---:|---:|---:|
| `documents_with_at_least_one_content_edge` | 106 / 148 | 127 / 148 | **125 / 148** |
| `MENTIONS_SERVICE` | 132 | 228 | **192** |
| `MENTIONS_CHANNEL` | 48 | 89 | **89** |
| `MENTIONS_VERIFICATION` | 37 | 73 | **73** |
| `MENTIONS_REQUIREMENT` | 18 | 15 | **15** |
| `MENTIONS_LOCATION` | 8 | 9 | **9** |
| `AVAILABLE_VIA` | 28 | 35 | **35** |
| `REQUIRES_VERIFICATION` | 16 | 31 | **31** |
| `REQUIRES_DOCUMENT` | 6 | 12 | **12** |
| total graph edges | 1,473 | 1,672 | **1,636** |

The content layer changed what the graph can answer. Phase 1 could only connect documents
that shared a *filing* decision (same category, tag, department). Phase 2 connects
documents that discuss the same *thing*: `Service::KYC Verification` reached degree 38 in
the pre-merge graph, one of the largest hubs, linking C05 SIM documents to C17 KYC
documents that no shared category or tag connects. (Exact degree shifts with the new
content; the structural point — content-layer hubs cross categories that metadata-layer
hubs cannot — still holds.)

Phase 1 remains reproducible: `graph_builder --metadata-only` regenerates
`nodes_metadata_only.json` and `edges_metadata_only.json` **byte-identical** (md5-verified)
to the Phase 1 files, and rebuilding twice produces identical bytes across all outputs.

---

## 3. Retrieval comparison

### 3.1 Baseline reproduction — DOES NOT MATCH, and the reason is in the data

The brief specified that the reproduced vector-only column must match Person A's stored
baseline (Recall@1 = 0.7586, @3 = 0.8966, @5 = 1.0). **It does not**, and the harness is
not the reason:

| | Recall@1 | Recall@3 | Recall@5 |
|---|---|---|---|
| Person A stored | 0.7586 | 0.8966 | 1.0000 |
| Reproduced here | 0.8966 | 1.0000 | 1.0000 |
| Delta | +0.1380 | +0.1034 | 0.0000 |

Evidence that this is a data-state change, not a harness bug:

1. Today's `data/vectorstore/faiss.index` holds **148 vectors** and
   `chunk_metadata.json` holds **148 chunks — one per document**, every `chunk_id` ending
   `_chunk_000`.
2. Person A's three stored evaluation files reference chunk ids ending `_chunk_001` and
   `_chunk_002` (e.g. `FAQ_C01_001_chunk_001`, `TARIFF_POSTPAID_2026H2_chunk_001`).
   Those vectors **do not exist** in today's index.
3. Their stored top-5 lists therefore contain duplicate `document_id`s (Q01 returns
   `FAQ_C01_001` twice). With one chunk per document that cannot happen — the top-5 chunks
   are 5 distinct documents, so document-level recall is mechanically higher.

So the stored baseline came from a superseded multi-chunk vectorstore that is no longer in
the repo. Rebuilding it would mean rewriting Person A's `data/`, which is out of bounds.

**What this does and does not invalidate:** both arms below run on the same current assets
through the same code path, so the vector-vs-graph comparison is valid. What is not valid
is comparing any number here against Person A's stored figures.

Retrieval reuses Person A's configuration directly — `ingestion.evaluate_retrieval` is
imported for `MODEL_NAME`, `INDEX_PATH`, `METADATA_PATH` and `BENCHMARK_PATH`. Their file
exposes no callable search function (only `main()` and `load_chunk_text`), so the
encode → `index.search` sequence is mirrored exactly rather than called.

### 3.2 Fusion method

Reciprocal Rank Fusion, `score(d) = Σ weight / (k + rank(d))`, k = 60. FAISS cosine
similarities and graph overlap counts are on incompatible scales and are never added
directly — only ranks are combined.

- Vector list: top 10 documents from FAISS.
- Graph list: top 20 candidates expanded from the top 5 vector documents, via shared
  `Service`, `Channel`, `VerificationMethod` or `Tag`.
- Weights: **vector 1.0, graph 0.5.** Declared before measuring, on the grounds that the
  graph list never sees the query — it is derived from the vector list's own hits, so it
  is strictly weaker evidence and must not outvote its own source. The full weight sweep
  is published below so the choice is auditable.

### 3.3 Main benchmark (29 questions, document-level)

| Arm | Recall@1 | Recall@3 | Recall@5 | MRR@5 | Precision@3 |
|---|---|---|---|---|---|
| vector_only | **0.8966** | 1.0000 | 1.0000 | **0.9483** | 0.5057 |
| graph_enhanced | 0.6552 | 1.0000 | 1.0000 | 0.8161 | **0.5287** |

`avg_docs_added_by_graph_per_query: 14.72`

**Graph fusion loses on this benchmark.** Recall@1 drops 24 points and MRR@5 drops 13.
Only Precision@3 improves, by 2.3 points. Recall@3 and Recall@5 are ties **at a ceiling**
(1.0 for both arms), not wins — there is nothing left to gain there.

Why it loses is not mysterious. Vector-only already answers 26 of 29 at rank 1 and 29 of 29
by rank 3; there is almost nothing for the graph to fix. Against that, expansion injects
~14.7 extra documents per query (10% of the corpus), and under RRF a document sitting
mid-pack in *both* lists can overtake a document that is rank 1 in the vector list alone.
That is the mechanism, and on a near-ceilinged benchmark it costs more than it returns.

**Fusion sensitivity** (same 29 questions — *not* a held-out set, so these rows are
diagnostics, not a menu to pick a winner from):

| Variant | Recall@1 | Recall@3 | MRR@5 | Precision@3 |
|---|---|---|---|---|
| RRF vector=1.0 graph=1.0 | 0.6207 | 0.9655 | 0.7701 | 0.4943 |
| **RRF vector=1.0 graph=0.5 (headline)** | 0.6552 | 1.0000 | 0.8161 | 0.5287 |
| RRF vector=1.0 graph=0.25 | 0.7241 | 1.0000 | 0.8506 | 0.5172 |
| vector=1.0 graph=0.5 + Category expansion | 0.7241 | 1.0000 | 0.8333 | 0.5517 |

The trend is monotone: the less the graph is allowed to say, the less damage it does, with
the limit at graph weight 0 being vector-only. On this benchmark that is the honest
summary — graph expansion has no headroom to exploit.

**Category expansion is reported separately and never folded into the headline.** The
benchmark has exactly one question per category, so expanding by `Category` is close to
handing the retriever the answer label. Its apparent improvement over the headline row
(+0.069 Recall@1) should be read as leakage, not lift.

### 3.4 Graph-dependent mini-benchmark (9 questions)

`knowledge_graph/graph_benchmark.json`. Questions were hand-written against the real corpus
so that the answer lives in an internal operational document (SOP, RCA, Policy, Training)
that a customer-phrased query does not lexically match, but which shares a Service or Tag
with the documents that query does match. Every expected document was read and genuinely
answers its question.

| Arm | Recall@1 | Recall@3 | Recall@5 | MRR@5 | Precision@3 |
|---|---|---|---|---|---|
| vector_only | 0.0000 | 0.7778 | 1.0000 | 0.3889 | 0.2593 |
| graph_enhanced | **0.3333** | 0.7778 | 1.0000 | **0.5685** | 0.2593 |

`avg_docs_added_by_graph_per_query: 14.11`

**This is where the graph earns its place, but the win is partial and specific:**

- **MRR@5: 0.3889 → 0.5685** (+0.18). The expected document is found meaningfully higher
  up.
- **Recall@1: 0.0 → 0.3333.** Vector-only never puts the right document first (that is by
  construction — see the bias note below); fusion does so for 3 of 9.
- **Recall@3: a tie at 0.7778**, and it is a tie with movement underneath, not a stalemate.
  One question gains and one loses, cancelling exactly. GQ02 gains: the Pune RCA climbs
  from rank 4 into the top 3. GQ04 loses: fusion lifts the fraud SOP from rank 10 to 4, but
  pushes TRN_003 — also a correct answer — from rank 2 down to 6, so nothing correct is
  left in the top 3. The other seven questions keep the same top-3 outcome, several with
  the expected document moving up inside it (which is what the MRR gain measures).
- **Recall@5 and Precision@3: ties.** Recall@5 is a ceiling (1.0 both arms).

**Selection bias, stated plainly:** a question was only included if no expected document
was already at vector rank 1 — i.e. the set is deliberately hard for semantic similarity.
That rule was applied to the *vector-only* arm and is blind to whether fusion helps, but it
still means vector-only's absolute numbers here are floored by construction. **These 9
numbers are not comparable with the 29-question benchmark**, and the set is far too small
for statistical significance. What it demonstrates is a mechanism, not a headline number.

---

## 4. Extraction validation

`knowledge_graph/validate_extraction.py` on a deterministic stratified sample of 20
documents spanning 13 document types (FAQ 7, KB 2, and one each of Coverage Map, Incident
Report, Policy, RCA, Release Notes, SOP, Sample Email, Support Transcript, Tariff
Catalogue, Training Manual, User Manual).

```
sample                 : 20 documents, 16 with at least one concept
predictions            : 49  (Service 24, Channel 11, VerificationMethod 8, Location 4, Requirement 2)
evidence integrity     : 49/49 (1.0000) triggers re-match on an independent re-scan
auto-verifiable subset : 34 (69.4%) fired on a multi-word phrase
flagged for review     : 6 of 49 carry a negation/hypothetical cue
provisional precision  : 0.9412  (32/34 clearly correct)
recall / f1            : n/a — needs human labels
```

**These are provisional and no labels were fabricated.** `output/extraction_gold_template.csv`
is written with one row per prediction (`document_id, concept, type, matched_terms,
evidence, predicted, is_correct, notes`) plus two blank `predicted=0` rows per document for
recording concepts the extractor **missed**. Fill `is_correct` and re-run the script; it
then reports measured Precision / Recall / F1 instead of the provisional figures.

**What the provisional number means, and its limits.** For a dictionary extractor, asking
"does the trigger appear in the text?" is the extractor's own rule — that check is circular
and returns 1.0 by construction. Two things make the reported figure informative instead:
an independent re-scan with freshly compiled patterns (catches stale outputs and
evidence-recording bugs — it passed 49/49), and a negation/hypothetical screen on the
evidence window, which is what allows the number to fall below 1.0. It is still an **upper
bound**: it cannot detect sense errors, and single-word triggers (`otp`, `kyc`, `recharge`,
`ont`) are excluded from the subset precisely because those are the ambiguous cases.

The screen is also conservative in the other direction. On inspection, the 6 flagged
predictions look correct — e.g. FAQ_C13_025's "I can't log in to the My NovaTel app — it
says 'OTP not received'" genuinely is about the app and OTP; the negation attaches to the
receipt of the OTP, not to the concept. That is the point: a human label is needed, and
the harness declines to guess.

**Recall cannot be estimated at all** without someone reading the documents and writing
down what was missed. It is reported as `n/a`, not as a number.

---

## 5. LIMITATIONS

Read this section before quoting any figure above.

### 5.1 `related_ids` are 100% unresolved

All **84** `related_ids` in the corpus point at document ids that do not exist among the
148 canonical documents (**55** distinct missing targets). `unresolved_rate = 1.0`.

They are preserved as stub `Document` nodes with `resolved=false` rather than dropped, so
the gap stays measurable and `output/edges.json` carries the full list of missing ids as a
work item. The consequence for the graph: **document-to-document connectivity from the
metadata layer is exactly zero.** Every apparent cross-reference in the corpus is broken.
Any traversal that looks like it follows document links is in fact going through a
Tag/Service/Category hub.

### 5.2 The C05 code conflict across branches

The two branches use the same code format for different vocabularies:

| Code | Document branch (this layer) | Structured branch (`structured/schema.py:77-89`) |
|---|---|---|
| `C05` | **SIM Card Services** | **`payment_transactions`** (`category_tag: "C05"`) |

These are unrelated meanings. **Do not join the branches on category code.** A join on
`C05` would silently attach SIM-card documentation to payment rows. Category names in
`ontology_schema.json` are document-derived and marked `name_source: document` or
`inferred`; they are not the structured taxonomy. An explicit crosswalk is required and has
not been built.

### 5.3 Content coverage is 125/148 (pre-merge baseline was 106/148, superseded)

**Pre-merge (superseded):** 42 documents (28%) produced no content edge at all — coverage
maps, FUP/speed explainers and outage RCAs, about *network conditions* rather than
*customer transactions*, so none of the five concept types applied.

**Current (post-merge):** coverage rose to 125/148 — 23 documents (16%) still produce no
content edge, down from 42. The rewritten text is longer and touches more of the concept
vocabulary incidentally (e.g. a coverage-map document now mentions "the My NovaTel app" in
a "how to check status" aside it didn't have before), which is a genuine coverage gain, not
an artifact. Checked the remaining 23 by category and title (not just trusting the count):
they cluster in C08/C09 (coverage, FUP/speed), C11 (international call rates), C12/C24
(device compatibility, VoLTE, IoT/M2M), C19 (privacy data requests), C21 (account closure),
C23 (enterprise connectivity) and billing/security incident reports — topics genuinely
outside the five-concept vocabulary (Service/Channel/VerificationMethod/Requirement/
Location), not documents the dictionary is failing to catch. Loosening triggers further to
cover them would manufacture false edges, not capture real signal.

Four declared concepts still found no evidence anywhere (`Channel::WhatsApp`,
`Requirement::PAN`, `VerificationMethod::PAN`, `VerificationMethod::Email Verification`);
they stay in the dictionary and are reported, but do not become orphan nodes.

Consequence for retrieval: for those 23 documents the graph offers only Tag and Category
bridges, so graph expansion cannot help a query whose answer lives there.

### 5.4 The main benchmark is at its ceiling

Vector-only already scores **Recall@5 = 1.0 and Recall@3 = 1.0** on the 29-question
benchmark. There is no headroom above rank 3 at all, and the only measurable room is
Recall@1, MRR@5 and Precision@3. Any "improvement" reported at @3 or @5 on this benchmark
is arithmetically impossible; any tie there is a **ceiling, not a win**.

This also means the benchmark cannot demonstrate the thing graph retrieval is for. It was
built to test semantic retrieval, and its questions are lexically close to their answer
documents — which is exactly the case where a graph adds nothing.

### 5.5 The vector-only baseline does not match Person A's stored numbers

See §3.1. The stored baseline came from a multi-chunk vectorstore that is no longer in the
repo; today's index is one chunk per document. Cross-run comparisons with Person A's saved
figures are invalid until the vectorstore is rebuilt. This also means the whole retrieval
comparison rests on a **single-chunk-per-document** index — with 148 documents and 148
vectors, FAISS is effectively doing whole-document matching, which favours the vector arm
and reduces what graph expansion can contribute.

### 5.6 Graph fusion is a net loss on the main benchmark

Stated plainly rather than buried: on the 29-question benchmark, graph-enhanced retrieval
is **worse** than vector-only on Recall@1 (−0.2414) and MRR@5 (−0.1322), better only on
Precision@3 (+0.0230). Do not deploy this fusion as a default retriever on
benchmark-like traffic. Its demonstrated value is confined to the graph-dependent question
type in §3.4.

### 5.7 The mini-benchmark is small and selection-biased

9 questions, hand-written by the same person who built the graph, with inclusion
conditioned on vector-only not already ranking an expected document first. That makes
vector-only's floor artificial and the absolute numbers meaningless outside the
within-set comparison. No statistical claim is made from 9 items.

### 5.8 Co-occurrence edges are heuristics

`AVAILABLE_VIA`, `REQUIRES_VERIFICATION` and `REQUIRES_DOCUMENT` come from a single rule:
both concepts appear in the same document. A KYC policy that lists every accepted document
produces `KYC Verification -[:REQUIRES_DOCUMENT]-> Passport` even though the policy is
listing alternatives. Every such edge carries `confidence="cooccurrence"`, a `support`
count and the backing document ids. Read `support` before trusting one; support 1 is a
single sentence's coincidence.

### 5.9 No held-out tuning set

The fusion weights were declared before measurement, but the sensitivity sweep in §3.3 was
computed on the same 29 questions it would be used to judge. There is no held-out split,
so no configuration should be selected on the strength of those rows.

### 5.10 Neo4j was not executed

Neo4j is not running on this machine (port 7687 closed). The loader, its allow-lists and
the payload shape were validated offline — all 363 node rows and 1473 edge rows group into
the 13 allowed labels and 16 allowed types with no non-scalar property values — but the
Cypher has never been executed against a live server. `neo4j_nodes` and
`neo4j_relationships` report `not run` until it is.

### 5.11 Bug found via the merge: bare "escalation" trigger fired on negated/heading text (fixed)

Same reporting pattern as the earlier extraction bugs: what was found, why, the fix, and how
it was verified — not just "fixed, trust me."

**What was found.** After the Sep 2026 merge, `evaluate_graph`'s ground-truth spotcheck on
`FAQ_C01_001` started returning an extra concept, `Service: Complaint Registration`, that
should not be there — the document is about updating a phone number, not filing a
complaint.

**Root cause.** Person A's new document template adds a standard "### Escalation" section
heading to many FAQs, and the `Complaint Registration` concept's dictionary included a bare
`escalation` trigger (`knowledge_graph/content_extractor.py`). Two distinct false-positive
sources, both traced to exact text before fixing anything:

1. The heading itself — `### Escalation` — fires the bare-word trigger regardless of what
   the section actually says. Corpus-wide check: 16 of 148 documents carry this heading,
   and 10 of those 16 have **no other mention of "escalation" anywhere in the body** — for
   those 10, the heading is the *only* reason the concept fired.
2. The section's own prose, on `FAQ_C01_001` specifically, explicitly **denies** an
   escalation applies: *"the store visit is the designated fallback rather than a general
   support escalation."* A bare-word match can't distinguish an assertion from its negation.

**The fix — narrow and rule-based, consistent with the existing dictionary approach (no
ML).** Two context checks, scoped only to the `("Service", "Complaint Registration",
"escalation")` trigger so no other concept's behaviour changes:

- **Negation guard:** suppress a match if a contrast/negation cue (`rather than`,
  `instead of`, `not a`, `not an`, `isn't a`, `is not a`) appears in the 60 characters
  immediately before it.
- **Heading-only guard:** suppress a match that is the *entire* content of a markdown
  heading line (`### Escalation` alone) — a section label is not a prose assertion, distinct
  from the same word inside a sentence.

Checked corpus-wide before adding the heading rule: of 30 total heading-only matches across
the whole corpus, only 2 belong to a different trigger (`Roaming` in two `TARIFF_*`
documents), and the fix is scoped narrowly enough not to touch them.

**Verification.**

| Check | Result |
|---|---|
| `FAQ_C01_001` spotcheck after the fix | Exact match to the original expected set — `Complaint Registration` gone, all five other concepts unchanged |
| Corpus-wide `MENTIONS_SERVICE` | 228 (post-merge, pre-fix) → 192 (post-fix) — 36 false-positive edges removed |
| Documents whose concept set changed because of the fix | 36 of 148, all losing only the spurious `Complaint Registration` |
| Documents that lost their *only* content edge (i.e. `Complaint Registration` was their sole concept) | 2 — `FAQ_C08_015`, `FAQ_C29_057` (both genuinely off-vocabulary: coverage/speed and device troubleshooting) |
| Unrelated triggers affected | 0 (the Roaming/tariff heading matches were confirmed untouched) |

This is now baked into `content_extractor.py` (`NEGATION_SENSITIVE_TRIGGERS`,
`_is_negated`, `_is_heading_only_match`) and re-runs identically on every future rebuild —
not a one-off manual correction to the data.

---

## 6. What would actually move the numbers

In rough order of expected value:

1. **Rebuild the multi-chunk vectorstore** (Person A's call). With one chunk per document,
   FAISS retrieval is whole-document matching and the benchmark ceilings immediately. Real
   chunking would restore headroom and make the graph comparison meaningful.
2. **A benchmark that is not one-question-per-category.** The current design makes Category
   expansion leaky and gives the graph nothing to fix.
3. **Fill the gold template** (~30 minutes) to convert provisional precision into measured
   Precision/Recall/F1 and expose the false negatives the dictionary is missing.
4. **Resolve the 84 dangling `related_ids`** — the only thing standing between this graph
   and real document-to-document structure.
5. **Sentence-scoped extraction** to promote co-occurrence edges into asserted facts,
   measured against this dictionary as the baseline.
6. **The category crosswalk** to unblock joining the two branches.

---

## 7. Reproducing every number in this report

```bash
python -m knowledge_graph.graph_builder                   # 363 nodes / 1473 edges
python -m knowledge_graph.evaluate_graph                  # Phase 1 + Phase 2 blocks
python -m knowledge_graph.validate_extraction             # extraction validation

# retrieval needs the environment with sentence-transformers + faiss
python -m knowledge_graph.evaluate_graph_rag --both       # both benchmarks + sweep
```

Full run order, environment notes and the Neo4j steps are in
`knowledge_graph/README.md`.
