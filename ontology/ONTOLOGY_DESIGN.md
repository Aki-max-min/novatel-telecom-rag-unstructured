# NovaTel Unstructured Knowledge Graph — Ontology Design (Phase 1)

**Scope:** the ontology and knowledge-graph layer built *on top of* the unstructured
ingestion pipeline. The pipeline and its outputs (`ingestion/`, `data/`, `structured/`,
`data/vectorstore/`) are read-only inputs here; this layer only adds `ontology/` and
`knowledge_graph/`.

**Input:** the 148 canonical documents in `data/processed/documents/*.json`.
Each carries exactly these fields: `document_id`, `title`, `document_type`, `category`,
`department`, `customer_scope`, `version`, `last_updated`, `source_authority`,
`related_ids`, `tags`, `content`, `file_path`, `file_type`.

## The one rule for Phase 1: deterministic only

No spaCy, no LLM, no ML, no embeddings, no text mining. Every node and every edge is
produced by reading a declared metadata field verbatim. `content` is deliberately *not*
mined — it is carried in the corpus but contributes nothing to the graph in this phase.

The consequence is that every number in the stats report is reproducible: run the
extractors twice on the same corpus and you get byte-identical `nodes.json`, `edges.json`
and `graph.json`. There is nothing to tune and nothing that drifts between runs. That is
the point of doing this phase first — it gives a trustworthy baseline that any later
entity-extraction work (which will be probabilistic) has to be measured against.

## What the graph looks like

The shape is a **hub-and-spoke graph**. Documents are the spokes; the shared metadata
values are hubs. Two documents are never joined directly by their metadata — they are
joined *through* the hub they share. A question like "what else does the Network
department own about coverage?" is answered by walking Document → Department → Document
and Document → Category → Document, with no text search involved.

### Node types

| Node | Key | Source field | Count | Why it exists |
|---|---|---|---|---|
| `Document` | `document_id` | `document_id` | 148 (+55 stubs) | The thing being described. Carries title, version, last_updated, file_type as properties. |
| `DocumentType` | value | `document_type` | 13 | Editorial form (FAQ, SOP, RCA, Policy…). Lets a retriever prefer an SOP over a chat transcript for a how-to question. |
| `Category` | code | `category` | 30 | NovaTel business category (C01–C29, GENERAL). The backbone of topical navigation. |
| `Department` | value | `department` | 13 | Internal owner. Answers routing and accountability questions. |
| `CustomerScope` | value | `customer_scope` | 4 | `all`, `prepaid`, `postpaid`, `enterprise`. Keeps a prepaid customer from being shown a postpaid-only policy. |
| `Tag` | tag string | `tags` | 68 | Free-form keywords. The densest *cross-category* connector — the only hub that regularly links documents filed under different categories. |
| `SourceAuthority` | value | `source_authority` | 1 | Provenance. Single-valued today ("Internal Knowledge Base"), modelled as a node anyway because trust weighting will need it once external sources land. |
| `Dataset` | derived | `document_id` prefix | 1 | `SciFact` when the id starts with `SCIFACT_`, else `NovaTel`. Currently all 148 are NovaTel; the node keeps benchmark data separable the moment SciFact documents are merged in. |

Hub nodes are **deduplicated on their key**: `Department::Network` is one node with 25
inbound edges, not 25 copies. `duplicate_node_rate` in the stats report exists to prove
this — it counts `(label, key)` pairs held by more than one node and should always read
`0.0`.

Node ids follow `<Label>::<key>`, so `Document::FAQ_012` and `Tag::billing` are
unambiguous across the whole graph.

### Relationship types

All eight relationships are directed and start at a `Document`:

| Relationship | Target | Source field | Edges |
|---|---|---|---|
| `BELONGS_TO_CATEGORY` | Category | `category` | 148 |
| `IS_TYPE` | DocumentType | `document_type` | 148 |
| `OWNED_BY_DEPARTMENT` | Department | `department` | 148 |
| `APPLIES_TO_SCOPE` | CustomerScope | `customer_scope` | 148 |
| `HAS_TAG` | Tag | `tags` | 208 (one per tag) |
| `AUTHORED_BY` | SourceAuthority | `source_authority` | 148 |
| `PART_OF_DATASET` | Dataset | `document_id` | 148 |
| `RELATED_TO` | Document | `related_ids` | 84 |

Seven of the eight are exactly one per document because their source fields are populated
on every document and single-valued. `HAS_TAG` is one edge per tag (114 of 148 documents
carry at least one tag). `RELATED_TO` is the only document-to-document edge.

## Category names are document-derived, not the structured taxonomy

The `category_catalog` in `ontology_schema.json` maps each code to a display name. Those
names were taken from how the codes are used **in these documents**. They are *not* the
same taxonomy as the structured branch: `structured/schema.py` attaches a `category_tag`
to each database table, and those assignments were made against table semantics rather
than document topics — the two schemes disagree on specific codes (for example the
structured branch tags its payments table `C05`, while in this corpus `C05` is SIM Card
Services).

**So: do not join the two branches on category code without an explicit crosswalk.** They
are different vocabularies that happen to share a code format. Building that crosswalk is
a known follow-up, and it belongs in the ontology layer, not in either branch.

Five names had no name string anywhere in the corpus and were assigned by the ontology
author. They are marked `"name_source": "inferred"` rather than being silently presented
as ground truth: **C01** Customer Profile & Account Management, **C11** International
Calling & ISD, **C15** Loyalty & Rewards, **C27** Accessibility Support, and **GENERAL**
General / Cross-Category. Every other code is marked `"name_source": "document"`. Any code
that shows up in a future document but is missing from the catalog is labelled
`"unmapped"` rather than dropped.

## `related_ids` are currently 100% unresolved

All 84 `related_ids` across the corpus point at document ids that **do not exist** among
the 148 canonical documents (55 distinct targets). `unresolved_rate = 1.0`.

These references are **not dropped**. For each dangling target, a stub `Document` node is
created with `resolved=false` / `stub=true` and empty title/version metadata, and the
`RELATED_TO` edge is written normally with `resolved=false` on the edge itself. That
choice is deliberate:

1. **The rate stays measurable.** Dropping the edges would make the corpus look internally
   consistent when it is not. The stats report surfaces `related_ids_unresolved: 84` and
   `unresolved_rate: 1.0` every run, so the gap cannot quietly disappear.
2. **The stubs are a work list.** `unresolved_targets` in `output/edges.json` names all 55
   missing documents. That list is exactly what someone needs to either locate the missing
   source files or correct the metadata.
3. **Re-resolution is free.** If those documents are ingested later, their real nodes
   replace the stubs on the next build and the existing edges become live — no edge
   rewriting needed.

Stubs are counted separately in the report as `StubDocument(unresolved): 55`, so the 148
real documents are never inflated by them.

## What the numbers say about the corpus

The graph is **one connected component**. That is not a sign of rich cross-linking — it is
a consequence of `SourceAuthority` and `Dataset` being single-valued: every document
attaches to the same two hubs, which alone makes the graph connected. The honest reading
is that `Tag`, `Category` and `Department` are where the real structure lives, and that
document-to-document connectivity is currently *zero* because every `RELATED_TO` edge ends
on a stub.

Average degree is 7.09 over 333 nodes and 1180 edges. Documents sit at degree 7–10 (their
seven mandatory hub edges plus tags and related links); hubs are high-degree by design.

## Deliberate non-goals in this phase

- **No entity extraction from `content`.** Products, plans, circles and error codes are
  all sitting in the document text. Pulling them out needs NLP and is Phase 2 — keeping it
  out of Phase 1 is what makes these numbers auditable.
- **No tag normalisation.** Tags are used verbatim: no case folding, no stemming, no
  merging of near-duplicates. The 68 distinct tags are already 68 distinct case-sensitive
  strings, so nothing is being lost today, but a normalisation pass is a future decision to
  be made explicitly rather than smuggled in.
- **No inferred edges.** Nothing like "these two documents are similar" or "this category
  is a parent of that one". Every edge traces to one field of one document.
- **No merge with the structured branch.** Blocked on the category crosswalk described
  above.

## Files

| File | Purpose |
|---|---|
| `ontology/ontology_schema.json` | Formal schema: node labels, relationship types, id convention, dangling-reference policy, category catalog. |
| `ontology/entity_definitions.json` | Per node type: description, source field, key field, properties. |
| `ontology/relationship_definitions.json` | Per relationship: type, from/to labels, source field, meaning. |
| `ontology/ONTOLOGY_DESIGN.md` | This document. |
| `knowledge_graph/entity_extractor.py` | Reads the 148 JSONs, emits deduplicated nodes (+ stubs). |
| `knowledge_graph/relationship_extractor.py` | Emits all edges, flagging unresolved `RELATED_TO`. |
| `knowledge_graph/graph_builder.py` | Builds the `networkx.MultiDiGraph`, writes graphml + JSON. |
| `knowledge_graph/evaluate_graph.py` | Loads the built graph, prints the Phase 1 stats block. |
| `knowledge_graph/requirements-kg.txt` | The one dependency this layer adds: `networkx`. |

## Running it

```bash
pip install -r knowledge_graph/requirements-kg.txt   # networkx only
python -m knowledge_graph.graph_builder              # writes knowledge_graph/output/
python -m knowledge_graph.evaluate_graph             # prints the stats block
```

Outputs land in `knowledge_graph/output/`: `novatel_kg.graphml`, `graph.json`,
`nodes.json`, `edges.json`.

---

# Phase 2 — Content Layer, Neo4j and Visualization

Phase 1 above is unchanged and still describes the metadata layer. Phase 2 adds a
second layer on top of it: telecom concepts pulled out of the document **text**,
then the whole graph mirrored into Neo4j.

The Phase 1 numbers still hold. `evaluate_graph` computes its Phase 1 block over
the metadata subgraph (`layer=metadata`), so it still prints 333 nodes / 1180
edges / 1 component / `unresolved_rate 1.0`, and `graph_builder --metadata-only`
still rebuilds the Phase 1 graph on its own.

## How content extraction works

**A curated pattern dictionary — nothing else.** `CONCEPT_DICTIONARY` in
`knowledge_graph/content_extractor.py` maps each canonical concept name to an
explicit list of trigger phrases. For every document, `title` and `content` are
scanned for each phrase; a hit creates one mention record.

spaCy is installed in this environment and is deliberately **not** used. Neither
is any model, embedding or LLM. The reason is auditability: with a dictionary,
every edge in the graph traces to a phrase somebody chose and can defend, and two
runs over the same corpus produce identical output. A statistical extractor buys
recall at the cost of both. Phase 2 is the baseline that a probabilistic
extractor would later have to beat.

**Matching is boundary-safe.** Phrases are matched case-insensitively but only on
non-alphanumeric boundaries — `(?<![A-Za-z0-9])phrase(?![A-Za-z0-9])`. This is
not decoration; the corpus punishes naive matching:

| Naive trigger | What it would wrongly match | What is used instead |
|---|---|---|
| `port` | `self-care **port**al` (16 documents) | `porting`, `port number`, `port into`, `portability`, `mnp`, `upc` |
| `pan` | `**Pan**-India` in every incident header | `pan card`, `permanent account number` |
| `store` | every "visit a store" | `retail outlet`, `retail pos` for Retail Outlet; `experience store` for the Experience Store |

**Every mention carries its evidence.** A `MENTIONS_*` edge stores
`matched_terms` (which triggers fired), `match_count`, `evidence_span` (the exact
matched text) and `evidence` (a whitespace-collapsed snippet of surrounding
text). Any assertion in the graph can be checked against the sentence that
produced it without reopening the corpus.

## VerificationMethod vs Requirement

The two overlap in the source vocabulary — Aadhaar, PAN and photo ID appear in
both lists — so the ontology draws the line by **what the phrase describes**:

- a phrase naming a **verification act** is a `VerificationMethod`: OTP, Video
  KYC, biometric, `aadhaar-based` e-KYC, `id verification`;
- a phrase naming a **document the customer must produce** is a `Requirement`:
  valid photo ID, address proof, Aadhaar, passport, PAN card.

This is why `valid photo ID` in FAQ_C01_001 produces `Requirement: Valid Photo ID`
and *not* `VerificationMethod: Photo ID` — that concept fires only on
verification-act phrasing such as `photo ID verification` or `original ID proof`.
Without this rule the ground-truth document would return two verification
methods instead of one.

## Ground truth: FAQ_C01_001

The extractor must return exactly six concepts for this document, and it does:

| Type | Concept | Triggers that fired |
|---|---|---|
| Service | Mobile Number Update | `update the mobile number`, `update alternate number`, `contact details` |
| Channel | My NovaTel App | `my novatel app`, `novatel app` |
| Channel | Self-Care Portal | `self-care portal`, `self-care` |
| VerificationMethod | OTP | `otp` |
| Location | NovaTel Experience Store | `novatel experience store`, `experience store` |
| Requirement | Valid Photo ID | `valid photo id`, `photo id` |

Nothing else fires on it. `evaluate_graph` re-checks this **from the built
graph** (not from the extractor) on every run, so a dictionary change that breaks
it shows up immediately in the stats block.

## What the content layer produced

- **30 concept nodes** from 34 declared: Service 14, Channel 5,
  VerificationMethod 5, Requirement 4, Location 2.
- **243 mention edges**: MENTIONS_SERVICE 132, MENTIONS_CHANNEL 48,
  MENTIONS_VERIFICATION 37, MENTIONS_REQUIREMENT 18, MENTIONS_LOCATION 8.
- **50 co-occurrence edges**: AVAILABLE_VIA 28, REQUIRES_VERIFICATION 16,
  REQUIRES_DOCUMENT 6.
- **106 of 148 documents** carry at least one content edge.

Four declared concepts found no evidence — `Channel::WhatsApp`,
`Requirement::PAN`, `VerificationMethod::PAN`, `VerificationMethod::Email
Verification`. They stay in the dictionary and are reported by the extractor, but
they do **not** become orphan nodes. NovaTel simply does not document a WhatsApp
channel or PAN-card requirement in this corpus.

The 42 documents with no content edge are not a bug. They are coverage maps,
speed/FUP explainers and outage RCAs — documents about *network conditions*
rather than *customer transactions*, so none of the five concept types applies.
Loosening triggers to cover them would manufacture false edges; the honest number
is 106/148.

## Co-occurrence edges are leads, not facts

`AVAILABLE_VIA`, `REQUIRES_VERIFICATION` and `REQUIRES_DOCUMENT` are built from a
single rule: both concepts appear in the same document. That is genuinely weak
evidence. A KYC policy that lists every accepted document produces
`KYC Verification -[:REQUIRES_DOCUMENT]-> Passport` even though the policy is
describing alternatives, not requirements.

So every such edge carries `confidence="cooccurrence"`, a `support` count (how
many documents back the pair) and `evidence_document_ids`. Pairs are aggregated:
one edge per pair, not one per document. **Read `support` before trusting an
edge** — `KYC Verification → Video KYC` at support 8 is a real pattern;
something at support 1 is one sentence's worth of coincidence.

Turning these into asserted facts needs sentence-level scoping (does the verb
attach the requirement to *this* service?), which is Phase 3 work.

## Node and relationship additions

| Node | Key | Source | Evidenced |
|---|---|---|---|
| `Service` | canonical name | `title` + `content` | 14 |
| `Channel` | canonical name | `title` + `content` | 5 |
| `VerificationMethod` | canonical name | `title` + `content` | 5 |
| `Requirement` | canonical name | `title` + `content` | 4 |
| `Location` | canonical name | `title` + `content` | 2 |

| Relationship | From → To | Confidence |
|---|---|---|
| `MENTIONS_SERVICE` | Document → Service | `pattern_match` |
| `MENTIONS_CHANNEL` | Document → Channel | `pattern_match` |
| `MENTIONS_VERIFICATION` | Document → VerificationMethod | `pattern_match` |
| `MENTIONS_REQUIREMENT` | Document → Requirement | `pattern_match` |
| `MENTIONS_LOCATION` | Document → Location | `pattern_match` |
| `AVAILABLE_VIA` | Service → Channel | `cooccurrence` |
| `REQUIRES_VERIFICATION` | Service → VerificationMethod | `cooccurrence` |
| `REQUIRES_DOCUMENT` | Service → Requirement | `cooccurrence` |

Concept nodes are keyed on the **canonical name**, not the matched text, so
`self-care portal` and `web self-care` collapse onto one `Channel::Self-Care
Portal` node. Every node and edge also carries `layer` (`metadata` or `content`),
which is what lets the evaluator slice the two apart.

## What the content layer changed about the graph

The graph goes from 333 nodes / 1180 edges to **363 nodes / 1473 edges**. More
importantly, it changes what the graph can answer. Phase 1 could only connect
documents that shared a *filing* decision — same category, same tag, same
department. Phase 2 connects documents that discuss the same *thing*, even when
they were filed apart: `SOP_C05_SIM_REPLACEMENT` and `FAQ_C05_010` reach the KYC
documents through `Service::KYC Verification` despite sitting in a different
category.

`Service::KYC Verification` at degree 38 is now the fourth-largest hub in the
graph, behind only the two trivially-connected metadata hubs and the FAQ document
type.

## Neo4j

`knowledge_graph/graph_loader.py` mirrors `output/graph.json` into Neo4j. It
connects via `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` (default
`bolt://localhost:7687`), creates one uniqueness constraint per label on `id`,
and uses `MERGE` for every node and relationship — so loading twice leaves the
database exactly as loading once did. After loading, it runs the verification
query (`MATCH (n) RETURN count(n)` and `MATCH ()-[r]->() RETURN count(r)`) and
prints both counts.

Labels and relationship types cannot be parameterised in Cypher, so they are
interpolated into the query string. Both are checked against a fixed allow-list
built from the ontology before any query is constructed.

`knowledge_graph/cypher_queries.cypher` holds ten example queries, each with the
business question it answers.

## Visualization

`knowledge_graph/visualize_graph.py` renders a readable slice, not the whole
hairball. Default is one category — its documents plus every concept they mention
— as both an interactive pyvis HTML and a matplotlib PNG, with a fixed layout
seed so the same subgraph draws the same picture twice. `--service-map` renders
the Service/Channel/Verification/Requirement map instead.

## Files added in Phase 2

| File | Purpose |
|---|---|
| `knowledge_graph/content_extractor.py` | Curated dictionary, mention pass, co-occurrence pass. |
| `knowledge_graph/graph_queries.py` | Seven NetworkX queries with a runnable demo. |
| `knowledge_graph/graph_loader.py` | Idempotent MERGE load into Neo4j + verification counts. |
| `knowledge_graph/cypher_queries.cypher` | Ten example Cypher queries with business questions. |
| `knowledge_graph/visualize_graph.py` | pyvis HTML + matplotlib PNG of a subgraph. |

Extended: `graph_builder.py` (content merge, `--metadata-only`),
`evaluate_graph.py` (Phase 2 block, ground-truth spotcheck, Neo4j counts),
`entity_extractor.py` / `relationship_extractor.py` (output filename parameter).

## Outputs

`knowledge_graph/output/` now holds:

| File | Contents |
|---|---|
| `novatel_kg.graphml`, `graph.json` | The full metadata + content graph (363 / 1473). |
| `nodes.json`, `edges.json` | Metadata-layer extractor dumps (Phase 1 shape). |
| `content_extraction.json` | Concept nodes, edges, per-document mentions, and the dictionary itself. |
| `novatel_kg_metadata_only.graphml`, `graph_metadata_only.json`, `nodes_metadata_only.json`, `edges_metadata_only.json` | The Phase 1 graph, rebuilt by `--metadata-only`. |
| `subgraph_C17.html/.png`, `service_map.html/.png` | Visualizations. |

## Running Phase 2

```bash
pip install -r knowledge_graph/requirements-kg.txt

python -m knowledge_graph.content_extractor FAQ_C01_001   # ground-truth check
python -m knowledge_graph.graph_builder                   # metadata + content
python -m knowledge_graph.graph_builder --metadata-only   # Phase 1 graph
python -m knowledge_graph.evaluate_graph                  # both stats blocks
python -m knowledge_graph.graph_queries                   # NetworkX query demo
python -m knowledge_graph.visualize_graph                 # HTML + PNG
python -m knowledge_graph.graph_loader                    # needs a running Neo4j
```

## Phase 3 candidates

- **Sentence-scoped extraction** to promote co-occurrence edges into asserted
  facts, measured against this dictionary baseline.
- **The category crosswalk** to the structured branch (still blocked, see Phase 1).
- **Resolving the 84 dangling `related_ids`** — still 100% unresolved.
- **Tag normalisation**, still deliberately not done.

---

# Phase 4 — The Structured Knowledge Graph (28 SQL tables)

Phases 1–3 above describe the **document** branch and are unchanged. Phase 4 adds the
second branch: the 28 relational tables as a knowledge graph. The two are separate graphs
in separate files, joined (when they are joined at all) by a **shared concept name** — never
by category code. See the crosswalk warning below; it is the single most important thing in
this section.

## Source of truth

`structured/schema.py` → `TABLE_SCHEMAS` is **imported**, never copied. It supplies the
primary key, the foreign keys and the `category_tag` for each of the 28 tables. Data comes
from `data/processed/structured/novatel_structured.db` (SQLite, opened read-only). If the
schema changes, the graph changes with it and nothing here needs editing.

## Two views, kept apart

| View | What it holds | Files |
|---|---|---|
| **Instance graph** | one node per row (43,928), one edge per foreign key (31,027) | `structured_kg.graphml`, `structured_graph.json`, `structured_nodes.json`, `structured_edges.json` |
| **Schema graph** | 28 `EntityType` nodes, 24 `StructuredCategory` nodes, 20 FK relationship-type edges, 28 `IN_CATEGORY` edges | `structured_schema_kg.graphml`, `structured_schema_graph.json` |

The schema graph is the map; the instance graph is the territory. Keeping them in separate
files stops a "how many customers are there?" query from accidentally counting the
`Customer` *type* node as a customer. The schema view is built from `TABLE_SCHEMAS` alone,
so it stays valid even against an empty database.

## Node identity

`<EntityType>:<primary_key>` — e.g. `Customer:1829`, `Invoice:5475`, `CDR:730112`.

EntityType is the PascalCase of the table with `_master` stripped and the plural
singularised: `customer_master` → `Customer`, `payment_transactions` → `PaymentTransaction`,
`escalation_cases` → `EscalationCase`. Telecom acronyms stay uppercase (`CDR`, `SIMInventory`,
`ESIMProfile`, `KYCRecord`, `OTTSubscription`, `VASSubscription`, `Coverage5G`) because
"Cdr" and "Kyc" read as typos in a graph browser. The full 28-row mapping is written out in
`knowledge_graph/structured_entity_extractor.py` rather than computed, so what each table
becomes is reviewable at a glance.

Note the deliberate punctuation difference: the document branch uses `Label::key` (double
colon), the structured branch `EntityType:pk` (single colon). Ids from the two graphs
therefore cannot collide, even loaded into one Neo4j database.

**Properties are a selection, not a dump.** Each node carries `entity_type`, `category`,
`source_table`, its primary key, and up to six columns matching a preference list
(status / type / name / date / amount fields) in declared column order. Foreign-key columns
are deliberately excluded — they are edges, and storing them twice invites the two copies to
disagree.

## Relationships

Every non-null foreign key becomes one edge, directed **child → parent**:

| Relationship | Child → Parent | Edges |
|---|---|---|
| `OF_CUSTOMER` | 14 tables → `Customer` | 15,956 |
| `FOR_PLAN` | `RechargeTransaction` → `Plan` | 5,259 |
| `PAYS_INVOICE` | `PaymentTransaction` → `Invoice` | 4,162 |
| `AT_SITE` | `NetworkAlarm` → `NetworkSite` | 3,049 |
| `ON_PLAN` | `Subscription` → `Plan` | 1,809 |
| `OF_DEVICE_TYPE` | `DeviceRegistry` → `DeviceConfig` | 507 |
| `ESCALATES_TICKET` | `EscalationCase` → `Ticket` | 285 |

`OF_CUSTOMER` deliberately **aggregates all 14 customer FKs into one relationship type**.
That is the design decision that makes the graph worth building: "everything about this
customer" becomes a single hop over one relationship instead of a fourteen-way SQL join.
`subscriptions.plan_id` and `recharge_transactions.plan_id` both point at `plan_master` but
are kept as *different* relationships (`ON_PLAN` vs `FOR_PLAN`) because subscribing to a
plan and recharging against one are different business facts.

## Foreign-key integrity is measured, not asserted

`fk_integrity_rate = 1.0`, `dangling = 0`, across all 31,027 FK values.

That number is computed, not assumed: every FK value is checked against the parent table's
real primary-key set before the edge is written, and a dangling value would be counted and
reported per relationship rather than silently dropped. There are also zero NULL FK values —
every FK column is fully populated.

This is the sharp contrast with the document branch, where `related_ids` are **100%
unresolved** (84 of 84 dangling). The relational data has perfect referential integrity; the
document metadata has none. Same repository, opposite ends of the quality scale — which is
exactly why the two branches are modelled separately rather than merged into one graph.

## THE CROSSWALK — and the warning that goes with it

**C01–C29 category codes are NOT consistent across the two branches. They MUST NOT be used
as a cross-branch join key.** The join key is the **shared domain concept name**.

Both branches independently assigned codes from the same-looking `C01`–`C29` space to
different things. Of the 28 structured entity types, only **8 agree** with the document
branch's meaning of their code; **20 conflict**. A join on `category_code` would therefore
be wrong roughly 70% of the time — and silently wrong, because the join would succeed and
return plausible-looking rows.

Worked examples of the collision:

| Code | Structured branch means | Document branch means |
|---|---|---|
| **C05** | `payment_transactions` — Payments | **SIM Card Services** |
| **C06** | `sim_inventory` — SIM Card Services | **Number Portability** |
| **C11** | `tickets` — Complaints & Tickets | **International Calling & ISD** |
| **C16** | `fraud_cases` — Security & Fraud | **Complaints & Grievances** |
| **C29** | `escalation_cases` — Complaints & Escalations | **Technical Support & Troubleshooting** |

Read `C05` on its own and you cannot tell whether it means payments or SIM cards. The codes
are not a shared vocabulary; they are two private vocabularies that happen to share a
format.

### Full crosswalk: structured entity ↔ shared concept ↔ document category

| Structured entity | Table | Struct. code | **Shared domain concept (the join key)** | Document category | Codes agree? |
|---|---|---|---|---|---|
| `CDR` | `cdr` | C27 | **Usage Records** | C09 Data Services & Speed | no |
| `CorporateAccount` | `corporate_accounts` | C21 | **Enterprise & Business Services** | C23 Enterprise & Business Services | no |
| `Coverage5G` | `coverage_5g` | C28 | **Network Coverage** | C08 Network Coverage & Outages | no |
| `Customer` | `customer_master` | C01 | **Customer Account** | C01 Customer Profile & Account Management | yes |
| `DeviceConfig` | `device_config` | C24 | **Device Compatibility** | C12 Device Compatibility | no |
| `DeviceRegistry` | `device_registry` | C24 | **Device Compatibility** | C12 Device Compatibility | no |
| `ESIMProfile` | `esim_profiles` | C07 | **SIM Card Services** | C05 SIM Card Services | no |
| `EscalationCase` | `escalation_cases` | C29 | **Complaints & Grievances** | C16 Complaints & Grievances | no |
| `FiberInventory` | `fiber_inventory` | C12 | **Broadband & FTTH Services** | C25 Broadband & FTTH Services | no |
| `FraudCase` | `fraud_cases` | C16 | **Security & Fraud** | C18 Security & Fraud | no |
| `Invoice` | `invoices` | C04 | **Billing & Invoices** | C04 Billing & Invoices | yes |
| `KYCRecord` | `kyc_records` | C17 | **KYC & Identity Verification** | C17 KYC & Identity Verification | yes |
| `NetworkAlarm` | `network_alarms` | C08 | **Network Outages** | C08 Network Coverage & Outages | yes |
| `NetworkSite` | `network_sites` | C08 | **Network Coverage** | C08 Network Coverage & Outages | yes |
| `Offer` | `offers` | C15 | **Offers & Promotions** | C14 Offers & Promotions | no |
| `Order` | `orders` | C25 | **New Connection Activation** | C22 New Connection Activation | no |
| `OTTSubscription` | `ott_subscriptions` | C14 | **Value Added Services** | C10 Value Added Services | no |
| `PaymentTransaction` | `payment_transactions` | C05 | **Payments** | C03 Recharge & Payments | no |
| `Plan` | `plan_master` | C02 | **Plan Catalogue** | C02 Plans & Subscriptions | yes |
| `PortingRequest` | `porting_requests` | C18 | **Number Portability** | C06 Number Portability | no |
| `RechargeTransaction` | `recharge_transactions` | C03 | **Recharge** | C03 Recharge & Payments | yes |
| `RetailOutlet` | `retail_outlets` | C23 | **Retail & Store Network** | — (no document category; store visits sit inside C05/C17 documents) | no |
| `RoamingUsage` | `roaming_usage` | C10 | **Roaming** | C07 Roaming | no |
| `SIMInventory` | `sim_inventory` | C06 | **SIM Card Services** | C05 SIM Card Services | no |
| `Subscription` | `subscriptions` | C02 | **Subscription** | C02 Plans & Subscriptions | yes |
| `Technician` | `technicians` | C23 | **Field Operations** | C29 Technical Support & Troubleshooting | no |
| `Ticket` | `tickets` | C11 | **Complaints & Grievances** | C16 Complaints & Grievances | no |
| `VASSubscription` | `vas_subscriptions` | C26 | **Value Added Services** | C10 Value Added Services | no |

The machine-readable version is `structured_document_crosswalk` in `ontology_schema.json`,
with `join_key: "shared_domain_concept"` and the warning carried in the data itself.

**How to join the branches correctly:** map both sides to the shared concept, then join on
that. `PaymentTransaction` (structured) and the "Recharge & Payments" documents meet at the
concept **Payments**, not at any code. Three concepts are many-to-one on the structured side
(`OTTSubscription` + `VASSubscription` → Value Added Services; `SIMInventory` + `ESIMProfile`
→ SIM Card Services; `Ticket` + `EscalationCase` → Complaints & Grievances), so a join on
concept fans out and must be aggregated deliberately.

## What the graph shape says

- **`Customer` is the hub**: 15,956 of the 31,027 edges (51%) terminate on 1,809 customer
  nodes. The busiest customers reach degree 23.
- **`CDR` is the mass**: 16,017 nodes, 36% of the graph — and **zero edges**, because the
  table has no foreign keys. It joins to customers by `msisdn`, which the schema does not
  declare as an FK, so no edge is invented for it. Six other tables are likewise
  standalone: `RetailOutlet`, `Technician`, `Offer`, `Coverage5G`, `CorporateAccount`,
  `SIMInventory`.
- **The graph is not connected, and that is correct.** Measured: **17,317 isolated nodes**
  (39% of the graph) across exactly those seven types, and **17,469 connected components**.
  The largest component holds 23,411 nodes — the customer/plan/invoice/ticket core. The
  next largest hold 30-34 nodes each: a network site with its alarms. This is a faithful
  reflection of the schema, not a defect in the build; inventing `msisdn` joins would be
  fabricating relationships the database does not declare.

## Files added in Phase 4

| File | Purpose |
|---|---|
| `knowledge_graph/structured_entity_extractor.py` | rows → instance nodes (imports `TABLE_SCHEMAS`) |
| `knowledge_graph/structured_relationship_extractor.py` | FKs → edges, with the per-relationship integrity check |
| `knowledge_graph/structured_graph_builder.py` | instance graph + schema graph, saved separately |
| `knowledge_graph/structured_graph_queries.py` | seven multi-hop queries |
| `knowledge_graph/structured_evaluate_graph.py` | the Phase 4 stats block |
| `knowledge_graph/structured_graph_loader.py` | batched, idempotent Neo4j load, one label per entity type |

Nothing in the document KG was modified. The Phase 1–2 entries in
`ontology_schema.json`, `entity_definitions.json` and `relationship_definitions.json` are
byte-identical to before Phase 4; the structured branch was added under new top-level keys
(`branches`, `structured_node_labels`, `structured_relationship_types`,
`structured_document_crosswalk`, `structured_entities`, `structured_relationships`).

## Running it

```bash
python -m knowledge_graph.structured_graph_builder     # 43,928 nodes / 31,027 edges
python -m knowledge_graph.structured_evaluate_graph    # the Phase 4 stats block
python -m knowledge_graph.structured_graph_queries     # multi-hop query demo
python -m knowledge_graph.structured_graph_loader      # needs a running Neo4j
```

---

# The Unified Graph — the shared Concept layer

Phases 1–4 above built two graphs that never touched: 148 documents on one side, 43,928
database rows on the other, **zero** relationships between them. This section adds the
bridge, and the bridge is one idea: **both branches map into a single shared concept
vocabulary, and are joined there.**

## The join rule, and why the obvious join is wrong

**Join on the CONCEPT NAME. Never on the C01–C29 code.**

The two branches independently assigned codes from the same-looking `C01`–`C29` space to
different things. Only **8 of 28** structured entity types agree with the document branch on
the meaning of their code. A join on `category_code` would not error — it would return
plausible-looking rows that are wrong:

| Code | Structured branch | Document branch | A code join would… |
|---|---|---|---|
| `C11` | `tickets` — Complaints | International Calling & ISD | attach support tickets to ISD documentation |
| `C18` | `porting_requests` — Portability | Security & Fraud | attach porting requests to fraud policy |
| `C05` | `payment_transactions` — Payments | SIM Card Services | attach payments to SIM-swap FAQs |
| `C16` | `fraud_cases` — Security & Fraud | Complaints & Grievances | attach fraud cases to complaint FAQs |
| `C29` | `escalation_cases` — Escalations | Technical Support | attach escalations to troubleshooting guides |

Every one of those joins succeeds silently. That is what makes the code a trap rather than
merely a limitation — nothing fails, the answer is just wrong. The concept name is the only
key with one meaning on both sides.

## The vocabulary is inherited, not invented

The concept vocabulary is exactly the **distinct `shared_domain_concept` values of the
Phase 4 crosswalk** — 23 concepts. `concept_bridge.py` reads them from
`ontology_schema.json`; it does not define its own list.

This is deliberate. If the bridge were free to name concepts, `KYC` and
`KYC & Identity Verification` would end up as two nodes and the join would quietly split in
half. Any mapping whose right-hand side is not already in that column is rejected at build
time rather than creating a parallel name.

## Three relationship types

```
(Document)-[:BELONGS_TO_CATEGORY]->(Category)-[:EXPRESSES_CONCEPT]->(Concept)
(Document)-[:MENTIONS_SERVICE]->(Service)  -[:EXPRESSES_CONCEPT]->(Concept)
                                             (Concept)<-[:REALIZES_CONCEPT]-(EntityType)
                                                          (EntityType)<-[:INSTANCE_OF]-(row)-[:OF_CUSTOMER]->(Customer)
```

| Relationship | From → To | Edges | Source |
|---|---|---|---|
| `REALIZES_CONCEPT` | EntityType → Concept | 28 | the Phase 4 crosswalk, one edge per row |
| `EXPRESSES_CONCEPT` | Category → Concept | 22 | crosswalk `document_category_code` |
| `EXPRESSES_CONCEPT` | Service → Concept | 11 | `service_concept_mapping` (explicit table) |
| `INSTANCE_OF` | any structured row → EntityType | 43,928 | the row's `entity_type` property |

Both mappings are explicit tables. There is **no fuzzy matching, no string similarity, no
embedding** anywhere in the bridge — a concept edge exists because someone wrote it down.

**`INSTANCE_OF` is the expensive one and it is not optional in practice.** Without it the
bridge reaches the `EntityType:Customer` *schema* node and stops: there is no path to any of
the 1,809 real customers. It is one edge per row, making it the largest relationship type in
the database. `--no-instance-of` skips it for schema-only bridging.

## What the bridge produced

- **23 Concept nodes**, **22 of which bridge both sides**.
- **61 cross-link edges** (28 `REALIZES_CONCEPT` + 33 `EXPRESSES_CONCEPT`), plus 43,928
  `INSTANCE_OF`.
- Database totals: **44,342 nodes / 76,489 relationships**, of which the document KG is still
  exactly 363/1,473 and the structured KG exactly 43,928/31,027 — the bridge added, it did
  not modify.

### The connectivity proof

Before the bridge, `shortestPath` between a Document and a Customer returned nothing. Now:

```
FAQ_C01_001 -[BELONGS_TO_CATEGORY]-> C01
            -[EXPRESSES_CONCEPT]->   Concept::Customer Account
            -[REALIZES_CONCEPT]->    EntityType:Customer
            -[INSTANCE_OF]->         Customer:1829
```

Four hops, through a Concept. The counterfactual is checked on every run: the same query
restricted to non-bridge relationships still returns **no path**. That absence is precisely
what the concept layer fixed, and reporting both together is what makes the claim
falsifiable rather than decorative.

## What is deliberately *not* bridged

Three document Services carry no concept edge, and that is the correct outcome:

| Service | Why unmapped |
|---|---|
| `DND Activation` | No DND table exists on the structured side. No concept realizes it. |
| `Refund` | Refunds live inside `payment_transactions`, which realizes **Payments**. There is no separate Refund concept. |
| `Loyalty Redemption` | Not in the seeded mapping, and no Loyalty concept exists. `Offers & Promotions` is the `offers` table — a different thing. |

Mapping any of them would produce an edge into a concept that nothing on the structured side
realizes: a bridge that bridges nothing, which looks like coverage and is not. One concept —
**Retail & Store Network** (`retail_outlets`) — is structured-only, because no document
category or service covers physical stores.

`VAS Subscription` sits in the mapping table but matches no document Service node, so it
produces no edge; it is reported rather than silently dropped.

## Reading the coverage table

`unified_queries.py` prints documents-vs-rows per concept, which turns the bridge into a
gap analysis. Two patterns stand out:

- **Usage Records**: 16,017 rows, 6 documents. The largest table in the business has the
  thinnest documentation.
- **Complaints & Grievances** and **KYC & Identity Verification**: 25 documents each,
  against 1,771 and 870 rows. The best-documented concepts.

That comparison is impossible without the bridge — it needs both branches counted against
one vocabulary.

## Files

| File | Purpose |
|---|---|
| `knowledge_graph/concept_bridge.py` | Builds the concept layer from the crosswalk; `--load` MERGEs it into Neo4j |
| `knowledge_graph/unified_queries.py` | `unified_concept_query`, KYC view, complaint view, bridge coverage |
| `knowledge_graph/unified_cypher_queries.cypher` | 8 cross-branch queries + 3 verification queries |
| `knowledge_graph/evaluate_unified_graph.py` | The cross-link stats block and the connectivity proof |
| `knowledge_graph/output/concept_layer.json` | The built layer: concepts, bridge edges, mapping, stats |

The Phase 1–4 entries in `ontology_schema.json`, `entity_definitions.json` and
`relationship_definitions.json` are byte-identical to before this phase (verified by diff);
the concept layer was added under new top-level keys `concept_layer`,
`concept_relationship_types`, `concept_entities` and `concept_relationships`.

## Running it

```bash
python -m knowledge_graph.concept_bridge              # build + report, no database
python -m knowledge_graph.concept_bridge --load       # MERGE into Neo4j (idempotent)
python -m knowledge_graph.evaluate_unified_graph      # the cross-link block + proof
python -m knowledge_graph.unified_queries             # cross-branch query demo
python -m knowledge_graph.unified_queries --concept "Number Portability"
```
