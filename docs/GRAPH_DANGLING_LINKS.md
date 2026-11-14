# The 84 RELATED_TO links in the document graph are all dangling

Read-only diagnosis by Person A, 2026-10-31. Nothing under `knowledge_graph/` was edited; the determinism check wrote its output outside the repo.

## What was measured
| Item | Value |
|---|---|
| `RELATED_TO` edges in `knowledge_graph/output/graph.json` | 84 |
| edges whose **source** is an indexed document | 84 of 84 |
| edges whose **target** is an indexed document | **0 of 84** |
| edges with both endpoints indexed (usable as a "see also" hop) | **0** |
| distinct missing target ids | 55 |
| target nodes in the graph | 84 stub nodes (`resolved: false`, `stub: true`) |
| the extractor's own counters (`related_ids_total` / `related_ids_unresolved`) | 84 / 84 |

"Indexed" = a `document_id` in `data/experiments/combined_retrieval/vectorstore/chunk_metadata.json` (SciFact excluded).

## Three examples (one per pattern)
| Link | Source indexed? | Target indexed? | The real id that exists |
|---|---|---|---|
| `FAQ_C01_001` -> `KB_C01_overview` | yes | no | no `KB_C01_*` document exists |
| `KB_C02_plan_expiry` -> `FAQ_C02_001` | yes | no | FAQ ids of category C02 are `FAQ_C02_003`, `FAQ_C02_004` |
| `RCA_INC_2026_0142` -> `INC_INC_2026_0142` | yes | no | `INC_C08_INC_2026_0142` |

## ID formats
* Graph node ids are `<Label>::<key>`; Document keys are plain document ids (`FAQ_C01_001`, `KB_C02_plan_expiry`, `RCA_INC_2026_0142`, `INC_C08_INC_2026_0142`).
* The link endpoints are the strings stored in each source document's `related_ids` field (for example `data/raw/unstructured/faq/FAQ_C01_001.json` has `"related_ids": ["KB_C01_overview"]`).
* The indexed ids follow three different schemes: KB documents end in a topic slug (`KB_C02_plan_expiry`), FAQ documents carry a global running number (`FAQ_C02_003`), incident reports carry the category code (`INC_C08_INC_2026_0142`).

## The three patterns behind all 84 links
| Pattern of the missing target | Edges | Distinct targets | What exists instead |
|---|---|---|---|
| `KB_Cnn_overview` (FAQ -> KB) | 58 | 29 | no document has the slug `overview`; 21 of the 29 categories have some other `KB_Cnn_*` document, 8 categories have no KB document at all |
| `FAQ_Cnn_001` (KB -> FAQ) | 21 | 21 | FAQ numbers are global, not per category (`FAQ_C02_003`, ...), so `..._001` does not exist; other FAQ documents of that category do (21 of 21) |
| `INC_INC_<year>_<n>` (RCA -> incident) | 5 | 5 | `INC_Cnn_INC_<year>_<n>`: inserting the category code finds a real document for **5 of 5** |

## Where the links are defined
* Source data: the `related_ids` lists in the documents (raw files under `data/raw/unstructured/`, copied into `data/processed/documents/*.json`).
* Edge creation: `knowledge_graph/relationship_extractor.py` lines 89-105 (one `RELATED_TO` edge per related id, flagged `resolved=False` when the id is not a canonical document id).
* Stub nodes: `knowledge_graph/entity_extractor.py` lines 174-177 ("Dangling related_ids become stub Document nodes rather than being dropped").
* This is documented, intentional behaviour of the builder. It faithfully reports what the documents say.

## Is the build deterministic?
Yes, measured: the full build (`load_documents` -> `extract_entities` / `extract_relationships` / `extract_content` -> `build_graph` -> `save_graph`) was run twice into scratch folders; `graph.json`, `nodes.json`,
`edges.json` and `novatel_kg.graphml` were byte-identical between the two runs and identical to the existing `knowledge_graph/output/graph.json` (sha256 prefix `4ca13a32eebaaeeb`). 148 documents read.
The links are therefore not a build-time flake.

## Best-evidenced cause
The `related_ids` stored in the source documents were written with placeholder or template identifiers (`..._overview`, `FAQ_Cnn_001`, incident ids without the category code) that do not follow the
naming scheme the real documents ended up with (topic slugs, global FAQ numbers, category-coded incident ids). It is a data / id-authoring problem, not a graph-builder bug.
*Inference, not verified:* I did not find the script that authored `related_ids` in the repository, so which step introduced the mismatch is not established.

## Consequences
* A one-hop expansion along `RELATED_TO` (incident <-> RCA, FAQ <-> KB) can never reach a document. The semantic layer in `integration/rag/semantic_layer.py` skips, counts and logs these links, so it is safe, but that part of it currently contributes nothing.
* Only Person B's shared-concept bridges (Service / Channel / VerificationMethod / Tag) produce graph neighbours today.

## Draft message for Person B
> Hi, while wiring the document graph into the RAG layer I checked the `RELATED_TO` edges. All 84 have a real source document, but none of the 84 targets is an indexed document (0 of 84 resolve; 55 distinct missing ids,
> all stub nodes). Three patterns: `FAQ_Cnn_*` -> `KB_Cnn_overview` (58 edges; no `overview` KB documents exist), `KB_*` -> `FAQ_Cnn_001` (21 edges; FAQ numbers are global, e.g. `FAQ_C02_003`), and `RCA_*` ->
> `INC_INC_<id>` (5 edges; the real ids are `INC_Cnn_INC_<id>`, so a rule "insert the category code" repairs 5 of 5). The builder is deterministic (two fresh builds are byte-identical) and is doing what its
> docs say with dangling ids, so I think the `related_ids` in the source documents are the problem. Could you decide the intended targets? Details and counts are in `docs/GRAPH_DANGLING_LINKS.md`. I have not changed anything
> under `knowledge_graph/`; our retrieval layer simply skips and counts these links for now. Is it OK for the incident links to be repaired by the category-code rule, and what should the KB/FAQ links point at?
