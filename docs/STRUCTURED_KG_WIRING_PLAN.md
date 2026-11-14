# Structured KG wiring plan (plan only; nothing implemented, no Person B file edited)

Written 2026-11-11 by Person A's side for the v4 report's "structured KG: not run (not wired into retrieval)" row. Status after inspection: the
flag exists, the graph exists as code, and nothing connects them. This document says what connecting them would take, what it would be
evaluated against, and what Person B must confirm first.

## 1. What exists today (verified in the repository)

| item | where | state |
|---|---|---|
| `QAConfig.use_structured_kg: bool = False` | `integration/qa/config.py:55` | declared with the comment "present in repo; not wired into retrieval"; **read by no code** (`grep -rn use_structured_kg` finds only the declaration and the v3 report's "not connected" list) |
| our structured path | `integration/rag/pipeline.py::StructuredSearchAdapter` -> `integration/structured_guard.guarded_structured_search` -> `structured/retriever.StructuredRetriever.search` (Person B) | SQL rows only: exact lookup / customer-scoped filter / aggregate count / **foreign-key follow** (`fk_follow`, Person B `aaefec2`: parent row + child rows through an allow-listed FK, customer-scoped) |
| QA system structured path | `integration/qa/retrieval.py::StructuredBackend` (`parse`, `can_execute`, `search`) used by `integration/qa/system.py::_retrieve_structured` | same retriever; the hybrid route decomposes the question into a structured and an unstructured sub-query |
| Person B's hybrid structured adapter | `hybrid/structured_adapter.fetch_customer_facts(customer_id, intents, ...)` | read-only sqlite, fixed parameterised SQL, session-customer scoped, data-minimised; no graph |
| structured KG builder | `knowledge_graph/structured_graph_builder.py` (`python -m knowledge_graph.structured_graph_builder`) | builds `knowledge_graph/output/structured_graph.json` (+ graphml, schema graph) from `structured/schema.TABLE_SCHEMAS` and the SQLite DB: 43,928 nodes / 31,027 FK edges per the README; **the output file is not present in this checkout** (`knowledge_graph/output/` holds only the document graph; `structured_graph.json` is git-ignored) |
| structured KG query API | `knowledge_graph/structured_graph_queries.py`: `load_graph(path) -> nx.MultiDiGraph`, `node_id(entity, key)`, `tickets_for_customer`, `customer_360`, `ticket_escalation_chains`, `invoice_payment_reconciliation`, `sites_with_most_alarms`, `top_hub_customers`, `widest_coverage_customer`, `plan_adoption` | networkx, in-process, no Neo4j needed; the Neo4j loader (`structured_graph_loader.py`) and `unified_queries.py` (concept bridge document<->structured) need a running Neo4j |
| relationship names | `knowledge_graph/structured_relationship_extractor.RELATIONSHIP_NAMES` (OF_CUSTOMER, ON_PLAN, PAYS_INVOICE, ...) | FK triples from `TABLE_SCHEMAS`; `OF_CUSTOMER` aggregates the 14 tables that point at `customer_master` |

So "structured KG" = an in-memory FK graph over the same SQLite rows the retriever already reads, plus multi-hop query functions. It adds no
data the database does not hold; it adds traversal.

## 2. What the arm would be

`B2 + structured KG`: for a question the parser resolves to a customer (or to a record with a customer), ask the structured KG for the
connected records the question needs (the multi-hop view) and put them in the structured candidate list BEFORE fusion, in the Common Result
Schema the retriever already emits (`source="structured"`, `dataset=<table>`, `record_id=<pk>`, `content`, `metadata`). Everything downstream
(RRF, per-source budget 5 db + 3 doc, generation, citation check, the judge, `classify`) stays unchanged, so the arm is comparable to B2.

Interface (proposed, in OUR code only):

```text
integration/structured_kg_adapter.py   (new)
    class StructuredKGAdapter:
        def __init__(self, graph_path=knowledge_graph.structured_graph_builder.INSTANCE_JSON_PATH)   # load_graph() once; raise a clear error if missing
        def expand(self, parsed: dict, rows: list[dict], top_k: int) -> list[dict]
            # parsed = StructuredRetriever's parsed query (table, record_id / filter, customer_id); rows = what the retriever returned
            # returns ADDITIONAL Common-Schema rows reached in the graph: for a Customer seed -> customer_360 slice limited to the
            # entity types the question names (Invoice, Ticket, PaymentTransaction, EscalationCase, ...); for an Invoice seed ->
            # invoice_payment_reconciliation; for a Ticket seed -> ticket_escalation_chains; never rows of another customer
integration/rag/pipeline.py::StructuredSearchAdapter.search
    if cfg.use_structured_kg: results += kg_adapter.expand(guarded.parsed, results, top_k)   (de-duplicated by (table, pk); retriever rows first)
integration/qa/retrieval.py::StructuredBackend.search   same hook for the QA system
integration/rag/rag_config.RagConfig                   gains `structured_kg: bool = False` (default unchanged; golden test must still pass)
```

Row rendering: reuse `StructuredRetriever._wrap_result` / `_build_content_string` through the retriever instance (they are public enough and
already produce the Common Schema), so KG rows look exactly like SQL rows to the prompt and to `rows_in_prompt` / `db_rowcov`.

## 3. Files to touch (ours) and files NOT to touch (Person B's)

Ours: `integration/structured_kg_adapter.py` (new), `integration/rag/pipeline.py` (one hook, default off), `integration/qa/retrieval.py` (one hook),
`integration/rag/rag_config.py` (flag), `integration/tests/test_structured_kg_adapter.py` (new: fake graph, no DB), the E14 harness arm table
(`eval/final_ablation/harness_fa.py`: a new arm `K` = B2 + structured KG, router OFF; and `C_*K` only if the ablation says K helps).

Not touched: `knowledge_graph/structured_graph_*.py`, `structured/`, `hybrid/`. If the query functions need a variant (for example
`customer_360` limited to entity types, or a `records_connected_to(node_id, depth=1)` primitive), that is a request to Person B, not an edit.

## 4. What Person B must confirm before any of this is built

1. **Build and freeze the graph file**: `python -m knowledge_graph.structured_graph_builder --skip-graphml` on the tracked SQLite DB, with its
   sha256 and the DB's sha256 recorded (the file is git-ignored; we need a reproducible build or a tracked artifact). Node counts should match
   the README's 43,928 / 31,027.
2. **Node id and row key conventions**: `node_id(entity, key)` and the entity-type -> table mapping (`entity_type`) so that a graph node maps
   back to (table, primary key) without guessing; whether composite keys exist.
3. **Customer scoping**: confirm that every traversal we would use is reachable from `customer_master` through `OF_CUSTOMER` only (no path that
   leaks another customer's rows), and whether `recharge_transactions` (msisdn-keyed) is attached to the customer in the graph.
4. **Overlap with `fk_follow`**: Person B's `StructuredRetriever.fk_follow` already returns parent + child rows for invoice->payment_transactions
   and ticket->escalation_cases. The KG arm must be defined as what fk_follow does NOT already do (depth-2 paths, customer-360 slices,
   aggregate views), otherwise the arm measures nothing new. Person B should say which questions of the 42 (and of their benchmark) need more
   than one FK hop.
5. **Freshness**: the graph is a snapshot of the DB; agree that the evaluation DB is frozen (it is: `data/processed/structured/novatel_structured.db`
   tracked) so a stale graph cannot contradict SQL rows.

## 5. How it would be evaluated

Same protocol as every arm in this report: 42 questions, 3 runs, same judge, seed 42, temperature 0, answer cache off, pre-declared before the
run; arm `K` = B2 + structured KG (router OFF) compared with B2 on correctness (strict / partial / lenient, paired McNemar + bootstrap),
database-row coverage (the metric the KG should move: rows the question needs that reach the prompt), prompt tokens and latency, and the
error-cause table (expect `retrieval` and `context` to move for db / cross / multi questions, nothing else). Then `C_V1 + K` only if K vs B2
is not negative. Questions whose SQL needs are satisfied by exact lookup already (most of the 15 db questions) cannot improve; the arm's room
is in the 6 cross and 7 multi questions. With 13 such questions the comparison has low power, which the report must say.

## 6. Risks

* Prompt budget: 5 db blocks is tight; KG rows compete with the retriever's own rows for the same 5 slots. Rows must be ordered retriever
  first, KG rows by graph distance, and the budget must not be raised for this arm (that would be tuning on the 42).
* Double counting: a KG row identical to a retriever row must be de-duplicated by (table, pk) before fusion, or RRF double-ranks it.
* Scope leak: any traversal not anchored at the question's customer is a privacy bug; the adapter must refuse to expand when `customer_id` is
  unknown (the guard's `not_executable` case).
* Status contract: our guard and Person B's retriever already disagree on `status["route"]` (see `results/final_ablation/failing_tests.md`);
  a third producer of structured rows should not add a third vocabulary.
* Cost: `load_graph` parses a 44k-node JSON once per process (seconds); acceptable for the harness, must be lazy in the app.

Until items 1 to 4 are confirmed, the structured KG row in every table stays "not run (not wired into retrieval)".
