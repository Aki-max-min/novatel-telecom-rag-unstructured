# Pre-declaration: graph merge fix measurement

Written 2026-11-11 (UTC), before any generation for this measurement (before its smoke test as well). Branch `exp/kg-hardening-eval`.
The fix is commit `d7b8e1c` (`integration/rag/pipeline.py::UnstructuredSearcher._semantic_merge`); tests `integration/tests/test_semantic_merge_order.py`
were written before the change (4 of 7 failed on the old code, log `02_tests_before_fix.log`; 19 of 19 pass after, `03_tests_after_fix.log`).
Nothing in this file is changed after results are seen.

## What changed in the code (and only this)

Old: after the CrossEncoder scored the pool (original FAISS candidates + graph neighbours), the pool was re-ranked by weighted RRF:
`1/(60 + rank)` for every chunk plus `graph_weight/(60 + graph_rank)` for chunks of a graph-list document. With nearly flat base scores a
graph-list chunk passed the CrossEncoder's best chunk from rank 11 (weight 0.15) or rank 61 (weight 0.5) whatever its own score; seeds got the
bonus only when they neighboured another seed, so the gold document was often the one without it.

Reproduced on `results/perf_report/raw_answers.jsonl` (v3 arm docgraph, run 1; `01_reproduce_personB_count.txt`): 17 document questions with
graph weight > 0; 44 documents ranked above the gold, all 44 in `semantic.neighbour_docs`; gold at rank 1 in 19 of 25 (B2) vs 10 of 25 (docgraph);
the five questions whose gold was not in the graph list fell from rank 1 to 5 (MH02), 6 (MH04), 7 (MH05) or out of the top 10 (RW_017, MH_RB_B05).

New: graph neighbours only JOIN the candidate pool; the final order is the CrossEncoder score alone (`hybrid_score` descending, tie-break by
`chunk_id`). `graph_weight` stays an on/off switch (> 0: the graph may add candidates). The "semantic" trace fields are kept. Person B's optional
suggestion (let resolvable RELATED_TO neighbours join the pool when graph_weight is 0.0) is NOT adopted here: it changes the query gate's
contract and would need its own measurement; recorded as a follow-up.

## Arms (3 runs x 42 questions, same protocol as the KG-hardening and final-ablation runs)

| arm | definition | exact settings | source |
|---|---|---|---|
| B2 | RAG baseline + per-source budget 5 db + 3 doc, no router, no layer | `RagConfig.b2()` | reused from `results/kg_hardening_eval/` (126 records; B2 has no layer and never calls `_semantic_merge`; the smoke stage verifies that the plain document search on all 42 questions returns the stored B2 run-1 chunk lists) |
| GF | B2 + graph expansion with the FIXED merge, v3 "docgraph" definition | `DocGraphOnlyLayer` (no ontology terms in the FAISS query, gate weight kept), `graph_expand` with NO hardening keyword arguments (legacy), `use_related_links=False`, router OFF | generated |
| GFL | GF + RELATED_TO hop (optional second arm, as Person B suggested) | as GF with `use_related_links=True` | generated |

Everything else identical: `qwen2.5:7b-instruct` Q4_K_M, temperature 0, seed 42, E14a prompts, SciFact filter ON, answer cache OFF, FAISS top-10 +
CrossEncoder, RRF k=60 between SQL and documents (unchanged; the fix concerns only the document-side graph merge), GRAPH_SEEDS 5, GRAPH_CANDIDATES 20,
max 2 chunks per added document, the same judge (full level, caches of v3 and KG-hardening seeded read-only), the 42 questions and gold.

## Reported

Correctness (partial, strict, lenient) with the paired test (42 pairs, exact McNemar, bootstrap 95% CI, seed 20261031) for GF vs B2, GFL vs B2,
GFL vs GF; relevance, groundedness, hallucination vs reference and vs context, citations, latency, prompt tokens, per category, original-22; the
retrieval table (R@1, R@3, R@5, R@10, MRR@10, 25 document questions); the "what the graph added" table (added chunks, how many are gold, gold rank
better / same / worse / lost vs B2, run 1). Expected by construction: the gold rank can only get worse when the CrossEncoder itself scores an
added chunk higher than the gold's chunk; every such case is listed with both CrossEncoder scores. No tuning on the 42; if any adjustment seems
needed it is stated and the run stops.

Interpretation rule fixed now: every earlier graph result (v3 docgraph / C, v4, the KG-hardening C_V0 / C_V1 / C_V1_links and Person B's hardening
and link verdicts in `hybrid/`-independent terms) was measured with the old merge, so those numbers describe the merge bug at least as much as the
graph. This measurement does not re-score them.

## Frozen

No knob changed after seeing results; one run of the protocol; questions, gold, judge prompts, scoring code, seeds, router untouched;
`results/perf_report/`, `results/kg_hardening_eval/` and `results/final_ablation/` not written to; outputs in `results/graph_merge_fix/`.
The generation stage refuses to start on battery power unless overridden; sleep-after is 0 on AC and DC.
