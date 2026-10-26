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


---

## 8. Phase 5 Findings (E13 prototype evaluated)

*Added after the first end-to-end evaluation of the `hybrid/` prototype (`hybrid/evaluate_hybrid.py`, per-question output in `hybrid/evaluation_results.json`). Written to be read without the commit history.*

**What was run.** The full pipeline — query gate (`hybrid/query_gate.py`) → weighted RRF fusion (k=60) + dedup (`hybrid/fusion.py`, `hybrid/dedup.py`) → controlled CrossEncoder rerank, pool capped at 20 (`hybrid/rerank.py`) — on your 29-question benchmark and the 9-question graph-dependent mini-benchmark, using the real 383-chunk index, the real document graph and the real `cross-encoder/ms-marco-MiniLM-L-6-v2`. Vector-only and blanket-graph (0.5, no gate, no rerank) were re-computed with the same harness and reproduce the earlier numbers exactly.

**This was ONE untuned run.** Gate thresholds (0.5 / 0.15 / 0.0) are unchanged since Phase 2 and nothing was adjusted after seeing results. Further solo tuning was deliberately avoided: query understanding is joint-design territory (Section 7), and tuning on these 38 questions would also contaminate them as an evaluation set.

### Results

| Main benchmark (29 Q) | R@1 | R@3 | R@5 | MRR@5 |
|---|---|---|---|---|
| vector-only | 0.7586 | 0.9310 | 1.0000 | 0.8529 |
| graph blanket (0.5) | 0.3793 | 0.8621 | 0.8966 | 0.6236 |
| **E13 hybrid (gated + rerank)** | **0.9310** | **1.0000** | **1.0000** | **0.9598** |
| *diagnostic: gate + fusion, no rerank* | 0.6207 | 0.8966 | 0.9310 | 0.7615 |

| Graph-dependent mini-benchmark (9 Q) | R@1 | R@3 | R@5 | MRR@5 |
|---|---|---|---|---|
| vector-only | 0.2222 | 0.6667 | 0.8889 | 0.4574 |
| graph blanket (0.5) | 0.5556 | 0.6667 | 1.0000 | 0.6944 |
| **E13 hybrid (gated + rerank)** | **0.2222** | **0.6667** | **0.8889** | **0.4759** |
| *diagnostic: gate + fusion, no rerank* | 0.4444 | 0.7778 | 1.0000 | 0.6426 |

Gate weight distribution over all 38 questions: 0.5 → 11, 0.15 → 16, 0.0 → 11.

### Finding 1 — Main benchmark: the gain is entirely the rerank, and adds nothing over your existing pipeline

All of E13's improvement over vector-only on the main benchmark is attributable to the CrossEncoder. With the rerank removed, gate + fusion alone scores R@1 0.6207 — *worse* than vector-only's 0.7586. The reranked result (0.9310 / 1.0 / 1.0) matches the Recall numbers in your existing `data/vectorstore/reranked_retrieval_evaluation.json` (FAISS top-10 + CrossEncoder: top1 0.9310, top3 1.0, top5 1.0) exactly. **As currently built, E13 adds no new value on general questions**; it reproduces what your reranker already achieved. (Only the top-line recall numbers were compared, not per-question rankings.)

### Finding 2 — Mini-benchmark: E13 ties vector-only and loses to blanket-graph

On recall, E13 ties vector-only (0.2222 / 0.6667 / 0.8889) and is below blanket-graph on R@1 (0.2222 vs 0.5556) and R@5 (0.8889 vs 1.0). Two diagnosed causes:

- **(a) The gate's proxy does not track graph-dependence.** `needs_personal_data` ("my/I" + an account fact) was chosen because the roadmap's Section 3 described graph value as relational/customer context. In practice, only 3 of the 9 mini-benchmark questions got weight 0.5; most of the questions where the graph helps are phrased impersonally ("What proof does a store need before handing over a duplicate SIM?") and got 0.15 or 0.0.
- **(b) The CrossEncoder undoes the graph's contribution.** The diagnostic row shows gate + fusion alone (R@1 0.4444, R@3 0.7778, R@5 1.0) is clearly better than the reranked result on this set. A text-similarity reranker demotes graph-found candidates precisely *because* they were found through relationships rather than text similarity, and this benchmark was constructed so the correct answers use internal/off-vocabulary phrasing relative to the customer's question.

### Evidence for the gate redesign: wrong or missed concept hints on real benchmark questions

1. **DND / promo (false positive).** "I registered for DND but I'm still receiving promotional calls…" → *Offers & Promotions*. The bare `promo` keyword matches "promotional"; DND has no concept in the vocabulary (no DND table), so the correct result is no match. (Known limitation from Phase 2, now confirmed on a real question.)
2. **5G / Device Compatibility.** "How do I check whether my handset supports NovaTel 5G and VoLTE?" → *Network Coverage* (via `5g`). The intended concept is *Device Compatibility*; "handset" is not a keyword.
3. **Enterprise plan.** "What does a NovaTel enterprise connectivity plan include for a business?" → *Plan Catalogue* (via `plan`). *Enterprise & Business Services* is the better fit.
4. **IoT SIM.** "We have thousands of IoT SIM cards. How can our organisation monitor their usage?" → *SIM Card Services* (via `sim`); the question is an enterprise/usage question.
5. **Bare-"number" false-personal flag.** `number` is in the account-fact list, so "How much will I be charged if I call or send an SMS to a number in another country?" is flagged `needs_personal_data=True` although it is a tariff question (and got no concept hint at all). "Are there any special recharge offers available specifically for my mobile number?" is similarly flagged and hinted *Recharge* rather than *Offers & Promotions*.

Other misses seen in the same run: "I was subscribed to a service I don't remember requesting" (no hint — `subscription` doesn't match "subscribed"), "…update the number on my account" (no hint), "agent blocked my SIM before finishing the identity checks" (SIM Card Services, KYC not detected). The full per-question gate output is in `hybrid/evaluation_results.json`.

### Implementation fix needed (not a design question)

`fuse_candidates` keys candidates by `record_id`. At chunk level, a document reached through different chunks in the vector and graph lists (e.g. `X_chunk_001` vs `X_chunk_000`) is scored as two separate entries, so its two RRF contributions are not summed. The evaluation harness works around this by reusing the vector list's chunk record_id for graph documents that are also in the vector list (making fusion effectively document-level). This needs a proper fix in `fusion.py` before chunk-level fusion is trusted.

### Open questions for the joint sync (posed, not answered)

1. **Gate signal.** Should the gate predict *graph-dependence* directly, with a signal other than personal-data detection — for example vocabulary overlap between the question and the corpus, as a proxy for "text search alone is likely to miss this"?
2. **Rerank treatment of graph-sourced candidates.** Should `controlled_rerank` treat candidates that appear only in the graph list differently — for example blending `rerank_score` with `fusion_score` rather than fully overriding the fusion order, or skipping pure-text reranking for candidates with no vector-list presence?
