# SciFact in the combined index: retrieval comparison

**Re-computed in this task** (retrieval only, no LLM, no E14a file written). Question set: the 14 E14a document questions (8 synthetic Q*, 6 TRAI RW_*) with their E14a gold documents. Settings: all-MiniLM-L6-v2 -> FAISS top-10 -> ms-marco-MiniLM-L-6-v2 CrossEncoder rerank of the 10; docs deduplicated by best chunk.

Indexes: old = `data/experiments/combined_retrieval/vectorstore` (1545 chunks, includes 125 SciFact chunks); clean = `data/experiments/combined_retrieval_clean/vectorstore` (1420 chunks).

| variant | n | R@1 | R@3 | R@5 | R@10 | MRR@10 |
|---|---|---|---|---|---|---|
| old (all 14) | 14 | 0.7857 | 1.0000 | 1.0000 | 1.0000 | 0.8571 |
| old+filter (all 14) | 14 | 0.7857 | 1.0000 | 1.0000 | 1.0000 | 0.8571 |
| clean (all 14) | 14 | 0.7857 | 1.0000 | 1.0000 | 1.0000 | 0.8571 |
| old (synthetic 8) | 8 | 0.8750 | 1.0000 | 1.0000 | 1.0000 | 0.9167 |
| old (TRAI 6) | 6 | 0.6667 | 1.0000 | 1.0000 | 1.0000 | 0.7778 |
| clean (synthetic 8) | 8 | 0.8750 | 1.0000 | 1.0000 | 1.0000 | 0.9167 |
| clean (TRAI 6) | 6 | 0.6667 | 1.0000 | 1.0000 | 1.0000 | 0.7778 |

SciFact chunks in the old index's FAISS top-10 (questions with at least one): none.
Questions whose ranked document list differs between old, old+filter and clean: none.

Per-question lists are in `docs/scifact_index_comparison.json`.
