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

### 3.1 Baseline reproduction — RESOLVED (close match, residual gap explained)

**Original finding (pre-merge, now superseded):** the reproduced vector-only column did
not match Person A's stored baseline (Recall@1 = 0.7586, @3 = 0.8966, @5 = 1.0), because
`data/vectorstore/` at the time held 148 vectors — one chunk per document, every `chunk_id`
ending `_chunk_000` — while the stored evaluation referenced `_chunk_001`/`_chunk_002`
vectors that did not exist in that index. The conclusion at the time was that the stored
baseline came from a superseded multi-chunk vectorstore no longer in the repo.

**Post-merge: that vectorstore is back, and the mismatch is now resolved as predicted.**
Person A's merge (Sept 2026) rebuilt `data/vectorstore/` as a genuine multi-chunk index —
383 chunks over 248 documents, suffix distribution `{'000': 248, '001': 122, '002': 13}` —
matching the shape the stored baseline always implied.

| | Recall@1 | Recall@3 | Recall@5 |
|---|---|---|---|
| Person A stored | 0.7586 | 0.8966 | 1.0000 |
| Reproduced against the restored 383-chunk index | **0.7586** | 0.9310 | **1.0000** |
| Delta | **0.0000** | +0.0344 (1 question) | **0.0000** |

Recall@1 and Recall@5 match **exactly**. That confirms this is genuinely the same index,
model and embeddings that produced the stored numbers — not a coincidence or a looser
tolerance. Recall@3 is not exact: it differs by exactly one question out of 29.

**That one-question gap was investigated, not shrugged off.** Per-question raw chunk
retrieval was checked directly against Person A's stored per-question results for all three
of her original top-3 misses (Q06, Q13, Q17): the raw ranked chunk list this harness
retrieves is **byte-identical** to hers — same documents, same similarity scores, same
order, for all three. The gap opens one step later, in how a chunk-level list becomes a
document-level top-3:

- **Person A's `evaluate_retrieval.py`** takes `document_id` from the raw top-*k* chunks
  without deduplication. For Q13 ("The OTP for signing into the My NovaTel app isn't
  arriving...") her raw top-3 chunks are `MAN_APP_001`, `SOP_C13_APP_ACCESS_ISSUES`,
  `MAN_APP_001` again — the same document appears twice, wasting a slot, so the expected
  `FAQ_C13_025` (raw rank 4) never enters her top-3. **Miss.**
- **This harness's `VectorRetriever.search()`** deduplicates to distinct documents before
  taking the top-*k*, so the repeated `MAN_APP_001` is skipped and `FAQ_C13_025` rises into
  deduplicated rank 3. **Hit.**

That is a genuine, identified methodology difference — document-level deduplication policy
— not a data problem, a harness bug, or an unexplained discrepancy. It is a deliberate
design choice in this harness (a retriever that shows a customer the same document twice in
a top-3 is arguably worse, not equivalent), documented here rather than silently changed to
match hers.

**Verdict: RESOLVED.** The original mismatch is explained and no longer open. The residual
one-question Recall@3 gap has a known, verified cause and is not evidence of a stale index.

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

**Current run, against the restored 383-chunk index and the post-fix 363-node/1,636-edge
document KG:**

| Arm | Recall@1 | Recall@3 | Recall@5 | MRR@5 | Precision@3 |
|---|---|---|---|---|---|
| vector_only | **0.7586** | 0.9310 | **1.0000** | **0.8529** | 0.4713 |
| graph_enhanced | 0.3793 | 0.8621 | 0.8966 | 0.6236 | 0.4023 |

`avg_docs_added_by_graph_per_query: 16.1`

**Graph fusion loses on every single metric this time — including Recall@5, which used to
be a ceilinged tie and is now an outright regression.** With the real multi-chunk index,
vector-only no longer sits at a Recall@3/@5 ceiling (0.9310 / 1.0000, not 1.0000 / 1.0000),
so there was genuine headroom for the graph to help. It didn't: Recall@1 drops 38 points,
Recall@3 drops 7, Recall@5 drops **10 points below vector-only's ceiling** (0.8966 vs
1.0000 — graph fusion is now actively making the top-5 worse on this benchmark, not merely
failing to improve it), MRR@5 drops 23, and Precision@3 also drops (this arm no longer
even wins on precision, unlike the earlier stale-index run). This is a clean, unambiguous
loss, reported as one.

**Before/after, stale index vs restored index (both under weighted RRF, vector=1.0/graph=0.5,
not tuned on this benchmark):**

| Metric | Pre-merge (stale 148-chunk index) vector / graph | Post-merge (restored 383-chunk index) vector / graph |
|---|---|---|
| Recall@1 | 0.8966 / 0.6552 | **0.7586 / 0.3793** |
| Recall@3 | 1.0000 / 1.0000 (ceiling) | **0.9310 / 0.8621** |
| Recall@5 | 1.0000 / 1.0000 (ceiling) | **1.0000 / 0.8966** |
| MRR@5 | 0.9483 / 0.8161 | **0.8529 / 0.6236** |
| Precision@3 | 0.5057 / 0.5287 (graph won) | **0.4713 / 0.4023** (vector wins) |
| avg docs added/query | 14.72 | **16.1** |

Every column got worse for both arms with the real index — vector-only was never actually
at Recall@3/@5 ceiling; that ceiling was an artefact of the stale single-chunk index
retrieving 5 trivially-distinct documents. The real multi-chunk index is a harder, more
realistic benchmark, and graph fusion's loss margin widened on it, not narrowed.

Why it loses is not mysterious. Expansion injects ~16 extra documents per query (11% of
the corpus), and under RRF a document sitting mid-pack in *both* lists can overtake a
document that is rank 1 in the vector list alone — the same mechanism as before, just with
more room for it to do damage now that vector-only isn't already perfect.

**The fusion-sensitivity sweep from the earlier (stale-index) run is not re-run here** —
the brief for this pass specified the headline weights only (vector 1.0/graph 0.5,
declared not tuned), and re-sweeping against a benchmark that already shows a clear,
widened loss would not change the conclusion. If the sweep is wanted again, run
`evaluate_graph_rag.py` without `--no-sweep`.

### 3.4 Graph-dependent mini-benchmark (9 questions)

`knowledge_graph/graph_benchmark.json`. Questions were hand-written against the real corpus
so that the answer lives in an internal operational document (SOP, RCA, Policy, Training)
that a customer-phrased query does not lexically match, but which shares a Service or Tag
with the documents that query does match. Every expected document was read and genuinely
answers its question. Re-run against the restored 383-chunk index and the post-fix document
KG (the question set and its selection rule are unchanged from the original pass):

| Arm | Recall@1 | Recall@3 | Recall@5 | MRR@5 | Precision@3 |
|---|---|---|---|---|---|
| vector_only | 0.2222 | 0.6667 | 0.8889 | 0.4574 | 0.2222 |
| graph_enhanced | **0.5556** | 0.6667 | **1.0000** | **0.6944** | 0.2222 |

`avg_docs_added_by_graph_per_query: 16.67`

**This is still where the graph earns its place, and the margin is larger than before:**

- **MRR@5: 0.4574 → 0.6944** (+0.24, vs +0.18 on the stale index). Larger gain than the
  original pass.
- **Recall@1: 0.2222 → 0.5556** (2 of 9 questions correct at rank 1 → 5 of 9). A real,
  larger win than the original pass's 0/9 → 3/9.
- **Recall@5: 0.8889 → 1.0000 — a genuine improvement, not a ceiling tie this time.**
  Vector-only misses one question entirely inside its top 5 on the restored index (it
  wasn't at ceiling here either); graph fusion recovers it. This is the one metric in this
  whole re-baseline where fusion produces an unambiguous, non-ceilinged win.
- **Recall@3 and Precision@3: ties** (0.6667 and 0.2222 respectively) — reported as ties,
  not wins, per the same rule as before.

**Selection bias, stated plainly, unchanged from the original report:** a question was only
included if no expected document was already at vector rank 1 on the *original* index — the
set is deliberately hard for semantic similarity, the rule was applied blind to whether
fusion helps, and vector-only's absolute numbers here are floored by construction. **These 9
numbers are not comparable with the 29-question benchmark**, and the set is far too small
for statistical significance. Re-running it against a different (now correct) index changed
the vector-only baseline numbers themselves (0.0/0.7778/1.0000 → 0.2222/0.6667/0.8889 on
Recall@1/3/5) since the underlying retrieval changed — a reminder that this set was never
meant to be compared across index versions any more than across benchmarks.

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

### 5.4 The main benchmark's ceiling was an artefact of the stale index — RESOLVED, and the news is worse for the graph, not better

**Original finding (superseded):** against the stale single-chunk index, vector-only scored
Recall@5 = 1.0 and Recall@3 = 1.0, leaving no headroom above rank 3, so any tie there was a
ceiling rather than a win.

**Current:** against the restored 383-chunk index, vector-only scores **Recall@3 = 0.9310,
Recall@5 = 1.0000** — there is now real headroom at Recall@3, and it was real all along;
the earlier ceiling was purely an artefact of the stale index trivially retrieving 5
distinct documents per query. With that headroom now open, graph fusion had a genuine
chance to show gains on the main benchmark. **It didn't — see §5.6, now the more important
finding, not less.**

### 5.5 The vector-only baseline mismatch is RESOLVED

See §3.1 for the full account. Person A's Sept 2026 merge restored `data/vectorstore/` to a
genuine multi-chunk index (383 chunks / 248 documents), matching the shape the stored
baseline always implied. Recall@1 and Recall@5 now reproduce **exactly**; Recall@3 differs
by one question, traced to a specific, verified document-deduplication policy difference
between this harness and Person A's `evaluate_retrieval.py`, not to stale data. The whole
retrieval comparison now runs on real multi-chunk retrieval, not the single-chunk
whole-document matching this section originally flagged as favouring the vector arm.

### 5.6 Graph fusion is a net loss on the main benchmark — the loss widened, and Recall@5 now actively regresses

Stated plainly rather than buried, updated against the restored index: graph-enhanced
retrieval is worse than vector-only on **every metric measured** — Recall@1 (−0.3793),
Recall@3 (−0.0689), **Recall@5 (−0.1034 — no longer a ceiling tie; this is a genuine
regression below vector-only's ceiling)**, MRR@5 (−0.2293), and Precision@3 (−0.0690, which
also flips from a graph win to a vector win). The margin is larger across the board than
the earlier pre-merge run, not smaller — removing the artificial ceiling gave the graph
room to lose more visibly, not room to win. Do not deploy this fusion as a default
retriever on benchmark-like traffic. Its demonstrated value is confined to the
graph-dependent question type in §3.4, where it now also shows a genuine (non-ceilinged)
Recall@5 gain in addition to the earlier MRR@5 and Recall@1 gains.

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

1. ~~**Rebuild the multi-chunk vectorstore.**~~ **DONE** (Sept 2026 merge). The stale
   single-chunk index that ceilinged Recall@3/@5 is gone; see §3.1/§3.3/§5.4-5.6. It did
   restore real headroom, as predicted — but that headroom went to vector-only, not to
   graph fusion, whose loss margin widened rather than closed.
2. **A benchmark that is not one-question-per-category.** The current design makes Category
   expansion leaky and gives the graph nothing to fix. Still open.
3. **Fill the gold template** (~30 minutes) to convert provisional precision into measured
   Precision/Recall/F1 and expose the false negatives the dictionary is missing. Still open;
   note the sample and provisional-precision numbers in §4 predate the merge's content
   rewrite and would need re-sampling against the current text to stay meaningful.
4. **Resolve the 84 dangling `related_ids`** — the only thing standing between this graph
   and real document-to-document structure. Still open.
5. **Sentence-scoped extraction** to promote co-occurrence edges into asserted facts,
   measured against this dictionary as the baseline. Still open.
6. ~~**The category crosswalk** to unblock joining the two branches.~~ **DONE** (Phase 4/5,
   after this list was first written) — see `structured_document_crosswalk` in
   `ontology/ontology_schema.json` and the shared Concept layer in
   `knowledge_graph/concept_bridge.py`.

---

## 7. Reproducing every number in this report

```bash
python -m knowledge_graph.graph_builder                   # 363 nodes / 1636 edges (post-merge, post-fix)
python -m knowledge_graph.evaluate_graph                  # Phase 1 + Phase 2 blocks
python -m knowledge_graph.validate_extraction             # extraction validation

# retrieval needs the environment with sentence-transformers + faiss
python -m knowledge_graph.evaluate_graph_rag --both       # both benchmarks + sweep
```

Full run order, environment notes and the Neo4j steps are in
`knowledge_graph/README.md`.
