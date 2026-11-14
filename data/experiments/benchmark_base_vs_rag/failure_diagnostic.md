# Generation-failure diagnostic — NovaTel E14 Base-vs-RAG

Read-only analysis of the 8 queries labelled `generation_failure`. Every value below is read from `answers.jsonl` / `scores.jsonl` / `benchmark_results.json`; nothing was re-run and nothing is estimated.

**Field provenance note.** The reference-chunk rank is read from the ORDER of `rag_evidence` (its `E1..En` ids are the fused rank order). `parsed_query` was never persisted by the benchmark, so the *matched keyword* is **not available** as a saved field; the `derived keyword` column is re-derived read-only by scanning the question against `KEYWORD_TABLE_MAP` in source order and is labelled as derived, not read. The structured *table* that actually fired IS saved (`rag_evidence[].dataset`).

## The 8 generation failures

| query | intended / observed | ref rank in fused context | struct / doc blocks | structured relevant? | derived keyword | first cited block | C / G / H | class |
|---|---|---|---|---|---|---|---|---|
| Q08 | unstructured_synthetic / unstructured | rank 1 (E1) | 0 / 5 | n/a (none) | outage -> network_alarms | no citation in answer | 1 / 2 / 0 | **MODEL** |
| RW_001 | unstructured_public / unstructured | rank 4 (E4) | 0 / 5 | n/a (none) | no keyword match | E1 (unstructured:trai_public) | 1 / 2 / 0 | **RANKING** |
| RW_010 | unstructured_public / unstructured | rank 1 (E1) | 0 / 5 | n/a (none) | no keyword match | E4 (unstructured:trai_public) | 0 / 2 / 0 | **NOISE** |
| RW_023 | unstructured_public / unstructured | rank 1 (E1) | 0 / 5 | n/a (none) | no keyword match | E3 (unstructured:trai_public) | 1 / 2 / 0 | **NOISE** |
| S03 | structured / hybrid | rank 1 (E1) | 3 / 3 | yes | invoice -> invoices | E1 (structured:invoices) | 1 / 2 / 0 | **CONTEXT-BUDGET** |
| S06 | structured / hybrid | rank 1 (E1) | 3 / 3 | yes | ticket -> tickets | E1 (structured:tickets) | 1 / 2 / 0 | **CONTEXT-BUDGET** |
| S09 | structured / hybrid | rank 1 (E1) | 3 / 3 | yes | kyc -> kyc_records | E1 (structured:kyc_records) | 1 / 2 / 0 | **CONTEXT-BUDGET** |
| S12 | structured / hybrid | rank 1 (E1) | 3 / 3 | yes | fraud -> fraud_cases | E1 (structured:fraud_cases) | 1 / 2 / 0 | **CONTEXT-BUDGET** |

Rank field read from: Q08: rag_evidence[0] (metadata.provenance.document_id=FAQ_C08_015); RW_001: rag_evidence[3] (metadata.provenance.document_id=PUBLIC_PDF_01_TELECOM_CONSUMERS_PROTECTION); RW_010: rag_evidence[0] (metadata.provenance.document_id=PUBLIC_PDF_04_QUALITY_OF_SERVICE_REGULATIONS); RW_023: rag_evidence[0] (metadata.provenance.document_id=PUBLIC_PDF_08_TELECOM_PERFORMANCE_APR_JUN_2025); S03: rag_evidence[0] (source=structured, dataset=invoices); S06: rag_evidence[0] (source=structured, dataset=tickets); S09: rag_evidence[0] (source=structured, dataset=kyc_records); S12: rag_evidence[0] (source=structured, dataset=fraud_cases)

## Context-budget evidence for the four structured failures

| query | rows retrieved (`n_structured_results`) | structured blocks that survived `top_n=6` | ground-truth anchors needed | anchors the answer got right | correctness |
|---|---|---|---|---|---|
| S03 | 5 | 3 | 5 | 3 | 1 |
| S06 | 5 | 3 | 5 | 3 | 1 |
| S09 | 5 | 3 | 5 | 3 | 1 |
| S12 | 5 | 3 | 5 | 3 | 1 |

Read this row-by-row: the structured retriever returned **5** rows, the deterministic ground truth requires **5** row anchors, but only **3** structured blocks survived the 6-block context budget — and the answer correctly reproduced **every one of the 3 it was shown**. Scoring 2 was mechanically impossible: two of the required rows were never put in front of the model. `context_builder.build_context(top_n=6)` combined with RRF's interleaving of the two sources splits the budget roughly 3 structured / 3 document, so multi-row SQL answers get truncated by construction.

## Classification counts

- **CONTEXT-BUDGET**: 4
- **NOISE**: 2
- **MODEL**: 1
- **RANKING**: 1

Definitions — CONTEXT-BUDGET: the needed evidence was retrieved but truncated out of the context window, and the answer used everything it was actually shown. RANKING: reference chunk present but not first and the answer cited a different block. NOISE: reference chunk was first, yet the answer anchored on a different (off-task) block. MODEL: reference chunk was first and the answer still came out wrong. UNCLEAR: rank not recoverable from saved data.

> **Correction.** An initial pass labelled the four structured failures `MODEL`, on the grounds that the right row sat at rank 1 and was cited first. The context-budget check above overturns that: the model behaved correctly on the evidence it received, so the failure belongs to context assembly, not to the model.

## S15 (negative control) and the 'all 8 structured were hybrid' count

- S15 question: `asdkjaslkdj random gibberish query`
- `n_structured_results` = **0**, `n_unstructured_results` = **5**
- structured blocks in its fused context: **0** (none)
- `observed_query_type` = **unstructured**
- `failure_type` = **correct**, rag correctness = **2** (correct abstention)

So S15 is the ONE intended-structured query whose structured side returned nothing: the parser found no table keyword in `asdkjaslkdj random gibberish query`, so `StructuredRetriever.search` returned `results: []`. With zero structured results and five unstructured ones, the harness labelled it `unstructured`, not `hybrid`.

- Observed-type counts across all 22 queries: `{'hybrid': 10, 'unstructured': 12}`
- Of the 8 **intended-structured** queries, observed types were: `{'hybrid': 7, 'unstructured': 1}`

That is the correction to the earlier phrasing: it is **7 of 8** intended-structured queries that came back `hybrid`, not all 8 — S15 is the exception, and it is the only query in the set where the structured retriever correctly declined to fire. Every other structured query also pulled 5 document chunks alongside its SQL rows, because the unstructured searcher applies no relevance threshold.
