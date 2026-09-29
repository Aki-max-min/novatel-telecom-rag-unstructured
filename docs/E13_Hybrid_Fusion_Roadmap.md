# NovaTel Telecom RAG — E13 Hybrid Fusion: Status & Proposed Next Steps
**From Person B (ontology / knowledge graphs) — for Person A (retrieval / ColPali)**
**Base: `main` @ commit `ca02c24`**

---

## 1. Where things actually stand vs. your experiment ladder

Your own architecture doc laid out E10–E13. Here's the honest update on where each one is *now*, after the merge:

| Stage | Your doc said | Actual status after merge |
|---|---|---|
| E10 — Combined + Metadata + ColPali | NEXT (yours) | Still yours, unchanged by this merge |
| E11 — Ontology + document graph | PLANNED | **Done.** Ontology + 363-node document graph, live in Neo4j, re-baselined against your 383-chunk corpus |
| E12 — Structured KG + document graph | PLANNED | **Done.** 43,928-node structured KG (28 SQL tables, 0 broken FK links) + cross-linked to the document graph via a shared concept layer, verified with a real Document→Customer path |
| E13 — Full integrated retrieval | FINAL TARGET | **Not started — this is the joint work this doc is about** |

So the ontology/graph half of the "Final Unified Architecture" diagram (§16 of your doc) is built and ready to be called. E13 is genuinely the next milestone, and it needs both of us.

---

## 2. Your own target architecture (§16), annotated with what exists today

```
USER QUERY
    │
QUERY UNDERSTANDING — intent + entities + telecom domain + retrieval hints
    │
SHARED TELECOM ONTOLOGY MAPPING                    ◄── ontology/ (built, Person B)
    │
PARALLEL CANDIDATE GENERATION
 ├─ Combined FAISS (Synthetic + Public)             ◄── yours, built
 ├─ Metadata-aware filtering / boosting             ◄── yours, built
 ├─ ColPali page-level retrieval                    ◄── yours, built
 ├─ Existing unstructured Document Graph            ◄── built (Person B) — knowledge_graph/graph_queries.py
 └─ Structured KG from 28 SQL tables                ◄── built (Person B) — knowledge_graph/structured_graph_queries.py
    │
CANDIDATE FUSION                                    ◄── NOT BUILT — this is E13
    │
ONTOLOGY + ENTITY + RELATIONSHIP SIGNALS             ◄── partially built — knowledge_graph/concept_bridge.py,
    │                                                     unified_queries.py give concept-level linking;
    │                                                     turning that into a *scoring signal* is E13 work
CONTROLLED CROSSENCODER / HYBRID RERANKER            ◄── yours (CrossEncoder exists); "controlled" part is E13
    │
FINAL TOP-K EVIDENCE
    │
EVIDENCE DEDUPLICATION + CONTEXT SELECTION           ◄── NOT BUILT
    │
RAG LLM                                              ◄── NOT BUILT (deliberately last, per your own eval philosophy)
    │
GROUNDED ANSWER + EVIDENCE / CITATIONS
```

**Bottom line:** every *candidate generator* in the diagram exists. What's missing is the box that combines them — fusion, ontology-aware scoring, controlled reranking, dedup/context selection, and generation.

---

## 3. The finding that should shape how fusion is designed

I ran an honest evaluation of graph-augmented retrieval against your real 383-chunk index (RRF fusion, vector weight 1.0 / graph weight 0.5, not tuned). The result is a clean, useful signal — not a "graph is good" or "graph is bad" story, but a **conditional** one:

| Benchmark | Vector-only Recall@1 | Graph-enhanced Recall@1 | Verdict |
|---|---|---|---|
| Main benchmark (29 general questions) | 0.7586 | 0.3793 | **Graph hurts** — floods the candidate pool (~16 extra docs/query), demotes good vector hits |
| Graph-dependent set (9 questions needing relational/concept context) | 0.2222 | 0.5556 | **Graph genuinely helps** — Recall@5 also improves 0.889→1.000, a real win, not a ceiling tie |

**Implication for E13's fusion design:** the graph signal should not be applied as a blanket RRF input on every query. It should be **conditional / query-aware** — triggered when query understanding detects the question needs relational context (a specific customer, an entity-linking need, a concept the graph resolves better than free text) and otherwise left out or down-weighted. This is exactly what the "QUERY UNDERSTANDING" and "SHARED TELECOM ONTOLOGY MAPPING" boxes at the top of your diagram are positioned to decide *before* candidate generation — worth designing them to also gate *how much* graph signal enters fusion, not just which FAISS index to hit.

---

## 4. What's callable right now (Common Result Schema compliant)

All of these already return results in the shared `{source, record_id, dataset, category, score, retrieval_method, content, metadata}` schema, so they can be merged into your fusion layer without adapting the format.

| File | Function / entry point | Returns |
|---|---|---|
| `knowledge_graph/graph_queries.py` | document-graph queries (category lookup, shared-concept 2-hop, service co-occurrence) | Document KG candidates |
| `knowledge_graph/structured_graph_queries.py` | customer-360, ticket→escalation chains, invoice/payment reconciliation, site→alarms | Structured KG candidates |
| `knowledge_graph/unified_queries.py` | `unified_concept_query(concept_name)` — one call returning **both** governing documents and structured entity instances for a concept | Cross-graph candidates (this is the E12 cross-link, ready to call) |
| `knowledge_graph/graph_augmented_retrieval.py` | the RRF fusion harness used for the evaluation above | Reference implementation — shows the fusion method and honest weighting already tested |
| `knowledge_graph/concept_bridge.py` | resolves a query concept to both sides' entity types | Useful inside query understanding to decide if the graph should be consulted at all |

---

## 5. Proposed E13 build order (joint)

1. **Query understanding + concept gate** *(joint design, whoever builds is fine)* — detect intent/entities, map to a shared ontology concept via `concept_bridge.py`, and decide: does this query need graph signal at all? (Personal/factual → yes, pull structured KG. General policy question → FAISS/metadata primary, document graph only for expansion, not injection.)
2. **Candidate fusion, RRF by rank, never raw score concatenation** — reuse the method already validated in `graph_augmented_retrieval.py` (vector similarity and graph-hop scores are on incompatible scales; this was already proven necessary in earlier phases).
3. **Conditional graph weighting** — implement the gate from step 1 as an actual weight multiplier in fusion, not a fixed constant. Start with weight 0 (pure vector) as the default, weight ~0.5 only when the gate fires. This directly encodes the finding in §3 instead of re-discovering it during E13 evaluation.
4. **Evidence dedup** — dedupe to distinct `document_id`/entity before top-K selection. (This exact bug — non-deduped chunks stealing top-K slots — is what caused the Q13 Recall@3 discrepancy described in the sync message. Worth fixing at this layer regardless of graph involvement.)
5. **Controlled CrossEncoder rerank** over the deduped, fused candidate set.
6. **RAG LLM generation** — deliberately last, per your own eval philosophy (§19 of your doc): keep retrieval and generation errors separable.
7. **Re-evaluate on both benchmarks** (general 29-Q and the graph-dependent 9-Q set) to confirm the conditional gate actually captures the win without the loss.

---

## 6. Gotchas already discovered (so E13 doesn't re-hit them)

- **Never concatenate FAISS similarity scores with graph-hop scores directly** — different scales, already proven necessary to avoid.
- **A candidate pool flooded with graph expansions demotes good rank-1 hits** — cap how many graph-sourced candidates enter fusion per query, don't inject all reachable neighbors.
- **Chunk-to-document dedup matters** — do it before computing any Recall@K, not just in the final answer.
- **If either graph is ever reloaded with `--reset` in Neo4j, reload order matters**: document KG first, then `concept_bridge.py --load` — `DETACH DELETE` silently strips the cross-graph bridge edges otherwise. Documented in `knowledge_graph/README.md`.

---

## 7. Open question for sync

Should the **query-understanding + concept gate** (step 1) live in your `ingestion`/retrieval code or in a new shared `hybrid/` module we both contribute to? Recommend the latter, since it's the one piece that genuinely depends on both sides' knowledge (your query intent detection + my concept/entity resolution) — matches the "joint integration" row in the responsibilities table from the original Future Work Plan.
