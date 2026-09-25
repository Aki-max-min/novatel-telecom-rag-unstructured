# NovaTel Knowledge Graph (`knowledge_graph/` + `ontology/`)

Ontology and knowledge-graph layer built on top of Person A's unstructured ingestion
pipeline. Reads the 148 canonical documents in `data/processed/documents/`; writes only
into `knowledge_graph/output/`. `ingestion/`, `data/`, `structured/` and
`data/vectorstore/` are read-only inputs and are never modified.

Full write-up, results and limitations: **[KG_REPORT.md](KG_REPORT.md)**.
Ontology design: **[../ontology/ONTOLOGY_DESIGN.md](../ontology/ONTOLOGY_DESIGN.md)**.

---

## Environments

Two different Python environments are involved, because the graph layer and the retrieval
layer have different dependencies.

| Task | Needs | Environment |
|---|---|---|
| Graph build, evaluation, queries, visualization, extraction validation | `networkx` (+ optional `pyvis`, `matplotlib`, `neo4j`) | any Python with `knowledge_graph/requirements-kg.txt` installed |
| Retrieval comparison (`graph_augmented_retrieval`, `evaluate_graph_rag`) | `sentence-transformers`, `faiss`, `torch` | the environment Person A's pipeline runs in |

On this machine the retrieval environment is the conda env **`rag-api`**:

```powershell
# graph-layer scripts
python -m knowledge_graph.<module>

# retrieval scripts (needs sentence-transformers + faiss)
C:\Users\ASUS\anaconda3\envs\rag-api\python.exe -m knowledge_graph.<module>
```

To find the right interpreter on another machine, use whichever one can run
`python -m ingestion.evaluate_retrieval`. Every script is run as a module (`python -m ...`)
from the **repository root**, so the `knowledge_graph` and `ingestion` packages resolve.

Install the graph-layer dependencies:

```bash
pip install -r knowledge_graph/requirements-kg.txt
```

`networkx` is required. `pyvis`, `matplotlib` and `neo4j` are optional — each feature that
needs one degrades with a clear message instead of failing.

---

## Run order

Steps 1–3 are the core pipeline; run them in order. Steps 4–7 are independent of each
other and can be run in any order once step 1 has produced the graph.

### 1. Build the graph

```bash
python -m knowledge_graph.graph_builder                  # metadata + content (default)
python -m knowledge_graph.graph_builder --metadata-only  # Phase 1 graph only
```

Writes into `knowledge_graph/output/`:

| File | Contents |
|---|---|
| `novatel_kg.graphml`, `graph.json` | Full graph: 363 nodes / 1473 edges |
| `nodes.json`, `edges.json` | Metadata-layer extractor dumps |
| `content_extraction.json` | Concept nodes, edges, per-document mentions, and the dictionary itself |
| `*_metadata_only.*` | Phase 1 graph (333 / 1180), byte-identical to the Phase 1 run |

Both modes are deterministic: rebuilding produces identical bytes.

### 2. Evaluate the graph

```bash
python -m knowledge_graph.evaluate_graph                 # Phase 1 + Phase 2 stats blocks
python -m knowledge_graph.evaluate_graph --metadata-only # Phase 1 block only
python -m knowledge_graph.evaluate_graph --skip-neo4j    # don't try to reach Neo4j
```

Prints the Phase 1 block (computed over the metadata subgraph, so it stays comparable to
the Phase 1 run), the Phase 2 block, the FAQ_C01_001 ground-truth spotcheck, and the Neo4j
counts (`not run` when Neo4j is unavailable).

### 3. Retrieval comparison — **needs the `rag-api` environment**

```bash
C:\Users\ASUS\anaconda3\envs\rag-api\python.exe -m knowledge_graph.evaluate_graph_rag --both
```

| Flag | Effect |
|---|---|
| *(none)* | Main 29-question benchmark + baseline check + fusion sweep |
| `--graph-benchmark` | The 9-question graph-dependent set only |
| `--both` | Both benchmarks |
| `--no-sweep` | Skip the fusion sensitivity sweep |

Writes `output/graph_rag_evaluation.json`. The baseline reproduction check is printed
first — see [KG_REPORT.md §3.1](KG_REPORT.md) for why it currently reports a mismatch.

Single-query demo:

```bash
C:\Users\ASUS\anaconda3\envs\rag-api\python.exe -m knowledge_graph.graph_augmented_retrieval "how do I update my registered number"
```

### 4. Extraction validation

```bash
python -m knowledge_graph.validate_extraction
```

Samples 20 documents (stratified across document types, deterministic), lists the concepts
extracted for each, and writes `output/extraction_gold_template.csv`.

**To get real Precision / Recall / F1:** open that CSV, set `is_correct` to `1` or `0` on
each prediction row, write any concepts the extractor *missed* into the blank
`predicted=0` rows, save, then re-run the same command. Until then the script reports
provisional precision only and `n/a` for recall and F1 — it will not invent labels.

### 5. Query the graph

```bash
python -m knowledge_graph.graph_queries
python -m knowledge_graph.graph_queries --category C17 --service "KYC Verification" \
    --document FAQ_C01_001 --department Network
```

Seven NetworkX queries with a printable demo: documents in a category, documents mentioning
a service, 2-hop neighbours via shared Service/Tag, a service's co-occurrence profile, top
hubs by degree, documents by department, and concept coverage.

### 6. Visualize

```bash
python -m knowledge_graph.visualize_graph                # category C17 subgraph
python -m knowledge_graph.visualize_graph --category C05
python -m knowledge_graph.visualize_graph --service-map  # Service/Channel/Verification map
```

Writes an interactive `.html` (pyvis) and a static `.png` (matplotlib) into
`output/`. Layout uses a fixed seed, so the same subgraph renders identically each time.

### 7. Inspect a single document's extraction

```bash
python -m knowledge_graph.content_extractor FAQ_C01_001   # concepts + triggers + evidence
python -m knowledge_graph.content_extractor               # whole-corpus summary
```

---

## Neo4j

Neo4j is optional. Without it, everything above still runs and the Neo4j counts report
`not run`.

### 1. Start a server

**Option A — Neo4j Desktop (easiest on Windows)**

1. Install from <https://neo4j.com/download/>.
2. Create a new local DBMS, set a password, click **Start**.
3. Confirm the DBMS shows *Active* and Bolt is listening on port 7687.

**Option B — Docker**

```bash
docker run --name novatel-neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/YourPassword -d neo4j:5
```

### 2. Set credentials

```powershell
$env:NEO4J_URI      = "bolt://localhost:7687"   # default if unset
$env:NEO4J_USER     = "neo4j"                   # default if unset
$env:NEO4J_PASSWORD = "YourPassword"            # required, no default
$env:NEO4J_DATABASE = "neo4j"                   # default if unset
```

### 3. Load

```bash
python -m knowledge_graph.graph_loader           # MERGE the whole graph, then verify
python -m knowledge_graph.graph_loader --verify  # counts only, writes nothing
python -m knowledge_graph.graph_loader --reset   # delete NovaTel nodes first (destructive)
```

The loader reads `output/graph.json`, creates one uniqueness constraint per label on `id`,
and `MERGE`s every node and relationship — running it twice leaves the database exactly as
running it once did. It finishes by running the verification query and printing
`neo4j_nodes` and `neo4j_relationships` (expected: **363** and **1473**).

If Neo4j is unreachable the loader prints startup instructions and exits with status 2
rather than a stack trace.

> **Operating note — reload order matters if the concept bridge is loaded.** When using
> `graph_loader.py --reset`, Neo4j's `DETACH DELETE` removes every relationship touching a
> deleted node — including bridge edges (`EXPRESSES_CONCEPT`) that originate on document-KG
> nodes (`Category`, `Service`) but were added later by `concept_bridge.py`, which
> `graph_loader.py` has no knowledge of. `REALIZES_CONCEPT` survives because it runs between
> `EntityType`/`Concept`, neither a document-KG label, but `EXPRESSES_CONCEPT` does not.
> **Always reload in this order: document KG first (`graph_loader.py`, `--reset` or not),
> then `concept_bridge.py --load`** to restore the bridge edges. `structured_graph_loader.py
> --reset` does not have this problem — it only deletes `:StructuredEntity`-labeled nodes,
> which the bridge's `EXPRESSES_CONCEPT` edges never touch.

### 4. Query

Open <http://localhost:7474> and use the ten example queries in
[`cypher_queries.cypher`](cypher_queries.cypher) — each carries a comment naming the
business question it answers (which FAQs mention OTP, SOPs owned by Network, services
available via the app, unresolved cross-references, and so on).

After loading, re-run `python -m knowledge_graph.evaluate_graph` and the `--- NEO4J ---`
section will show live counts instead of `not run`.

---

## File map

| File | Purpose |
|---|---|
| `entity_extractor.py` | Metadata nodes (deduplicated) + stubs for dangling `related_ids` |
| `relationship_extractor.py` | Metadata edges, flagging unresolved `RELATED_TO` |
| `content_extractor.py` | Curated concept dictionary; mention pass + co-occurrence pass |
| `graph_builder.py` | Assembles the NetworkX graph; `--metadata-only` for Phase 1 |
| `evaluate_graph.py` | Phase 1 + Phase 2 stats blocks and ground-truth spotcheck |
| `graph_queries.py` | Seven NetworkX queries + demo |
| `graph_augmented_retrieval.py` | Vector search (Person A's FAISS) + graph expansion + RRF |
| `evaluate_graph_rag.py` | Vector-only vs graph-enhanced on both benchmarks |
| `graph_benchmark.json` | 9 hand-written graph-dependent questions |
| `validate_extraction.py` | Stratified sample, gold template, P/R/F1 |
| `graph_loader.py` | Idempotent MERGE load into Neo4j + verification |
| `cypher_queries.cypher` | Ten example Cypher queries |
| `visualize_graph.py` | pyvis HTML + matplotlib PNG of a subgraph |
| `requirements-kg.txt` | `networkx` required; `neo4j`, `pyvis`, `matplotlib` optional |
| `KG_REPORT.md` | Full report: ontology, stats, retrieval results, limitations |

---

## Structured knowledge graph (Phase 4)

A second, separate graph over the 28 SQL tables. It shares this package but not a single
output file with the document KG: every artefact is prefixed `structured_`.

`structured/schema.py` -> `TABLE_SCHEMAS` is imported as the source of truth for primary
keys, foreign keys and category tags; data is read from
`data/processed/structured/novatel_structured.db` (read-only). Only `networkx` is needed -
the retrieval environment is not involved.

```bash
python -m knowledge_graph.structured_graph_builder      # 43,928 nodes / 31,027 edges
python -m knowledge_graph.structured_graph_builder --skip-graphml   # JSON only, faster
python -m knowledge_graph.structured_evaluate_graph     # the Phase 4 stats block
python -m knowledge_graph.structured_evaluate_graph --customer 1829 --skip-neo4j
python -m knowledge_graph.structured_graph_queries      # 7 multi-hop queries
python -m knowledge_graph.structured_graph_queries --customer 1222
python -m knowledge_graph.structured_entity_extractor       # nodes only
python -m knowledge_graph.structured_relationship_extractor # edges + FK integrity report
```

### Outputs

| File | Contents |
|---|---|
| `structured_kg.graphml` | instance graph: one node per row, one edge per FK |
| `structured_graph.json` | instance nodes + edges + all build stats (what the queries load) |
| `structured_nodes.json` | instance nodes + extraction stats |
| `structured_edges.json` | FK edges + the per-relationship integrity report |
| `structured_schema_kg.graphml` | schema view: EntityType + StructuredCategory nodes |
| `structured_schema_graph.json` | schema view as JSON |

### Neo4j for the structured graph

Same connection variables as the document loader (see above). Nodes get their EntityType as
a label (`:Customer`, `:Invoice`, `:CDR`, ...) plus a shared `:StructuredEntity` label, so
the structured graph can be counted or deleted without touching the document KG.

```bash
python -m knowledge_graph.structured_graph_loader                 # batched MERGE + verify
python -m knowledge_graph.structured_graph_loader --verify        # counts only
python -m knowledge_graph.structured_graph_loader --schema-graph  # also load the schema view
python -m knowledge_graph.structured_graph_loader --reset         # delete structured nodes first
```

Writes are batched at 1,000 rows per statement (43,928 nodes, 31,027 edges) and use `MERGE`
throughout, so a second run is a no-op. Expected verification counts: **43,928** nodes and
**31,027** relationships, scoped to `:StructuredEntity`.

### Do not join the two branches on category code

`C01`-`C29` codes mean different things on each side - only 8 of 28 structured entity types
agree with the document branch. Join on the **shared concept name** in
`structured_document_crosswalk` (`ontology_schema.json`) instead. Full table and the
C05/C06/C11/C16/C29 conflicts are in
[../ontology/ONTOLOGY_DESIGN.md](../ontology/ONTOLOGY_DESIGN.md#phase-4--the-structured-knowledge-graph-28-sql-tables).

### Phase 4 file map

| File | Purpose |
|---|---|
| `structured_entity_extractor.py` | rows -> instance nodes (28 EntityType mapping lives here) |
| `structured_relationship_extractor.py` | FKs -> edges, measured integrity per relationship |
| `structured_graph_builder.py` | instance graph + schema graph, saved separately |
| `structured_graph_queries.py` | tickets, customer-360, escalation chains, reconciliation, site alarms, hubs, plan adoption |
| `structured_evaluate_graph.py` | Phase 4 stats block |
| `structured_graph_loader.py` | batched idempotent Neo4j load, label per entity type |
