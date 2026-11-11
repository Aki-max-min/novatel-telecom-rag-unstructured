# E13 graph-fusion fix: the graph is a candidate source, never a ranker

## Root cause (verified on Person A's recorded v3 runs, graph-only arm, and reproduced on `hybrid/fusion.py`)

The old merge gave every candidate `1/(60+rank)` and added `graph_weight/(60+graph_rank)` to candidates that are in
the graph list. The base scores are almost flat - rank 1 = **0.01639**, rank 2 = **0.01613** (gap 0.00026) - while the
bonus is **0.0025** at weight 0.15 and **0.0082** at weight 0.5. So graph membership outranked relevance:

- at weight 0.15 a graph member passed the best candidate from vector rank **11** (1/61 - 1/71 = 0.0023 < 0.0025);
- at weight 0.5 from vector rank **61** (1/61 - 1/121 = 0.0081 < 0.0082);
- the top documents are the seeds of the expansion, and a seed only gets the bonus if it is linked to another seed,
  so the correct document was often the one left *without* the bonus.

Evidence from the v3 runs: on the 17 questions where the graph was active, **all 44 documents ranked above a missed
gold document were graph-list members**, and gold at rank 1 fell from **19/25 to 10/25**. The same arithmetic was in
`hybrid/fusion.py::fuse_candidates` (the "graph" and "links" lists each added `weight/(k+rank)`); reproduced there
before the fix: with weight 0.15, a vector rank-11 document that is graph rank 1 moved to position 1.

## The fix (before/after rule)

| | before (weighted RRF) | after (append-only) |
|---|---|---|
| vector documents | `1/(k+rank)` + bonus if graph/link member | keep their vector order verbatim, no boost |
| graph/link-only documents | interleaved by `weight/(k+rank)` | **appended after all vector documents** - links first, then concept candidates, each in its own list order, deduplicated by document key |
| `graph_weight` / `link_weight` | scaled the bonus | pure on/off switches (> 0 include, <= 0 exclude); 0.15 and 0.5 give identical output |
| ranking | fusion arithmetic | the CrossEncoder rerank stage only |
| `fusion_score` | summed contributions | `1/(k+position)` over the final order - strictly decreasing, so later stages sorting by it preserve the order |

`fuse_candidates` keeps its signature, the document-level keying, the output fields (`fusion_score`,
`fusion_sources`, `fusion_doc_key`) and non-mutation; `fusion_sources` still records graph/link membership for the
trace. `hybrid/rerank.py`, `hybrid/query_gate.py` and `graph_expand` are unchanged;
`knowledge_graph/graph_augmented_retrieval.py::graph_enhanced_search` keeps the old merge (it reproduces the Phase 3
numbers) with a docstring note that it is the superseded design. The gate still acts per question as the on/off for
the concept-candidate list (a question with no concept hint gets weight 0.0 = concept list excluded); links join
whatever the gate says. The default rerank mode (`rrf_blend`) blends fusion position with the CrossEncoder rank, so
appended documents still have to earn their way up through the CrossEncoder.

Tests updated because they hard-coded the old bonus arithmetic (none deleted):
`test_fusion.py::test_weight_half_breakdown` (hand sums -> positional scores, order A,C,B,D -> A,B,C,D),
`test_fusion.py::test_fuse_and_select_three_questions` (same order change),
`test_fusion.py::TestDocumentLevelKeying::test_chunk_and_bare_id_fuse_as_one_document` (X = 1/61+0.5/62 -> 1/61),
`test_links.py::test_linked_neighbour_of_a_top3_seed_enters_fusion_even_at_gate_weight_zero` (0.3/61 -> 1/65, appended last),
`test_links.py::test_concept_list_is_untouched_by_links` (exact-score equality -> relative order + sources: positional
scores shift when the link block is inserted before the graph block),
`test_links.py::test_links_off_output_is_identical_to_the_current_behaviour` (A = 1/61+0.5/63 -> 1/61).

## Measurement rule (DECLARED BEFORE THE RUN; this section is committed before any measurement)

One run, dev sets only - main 29, mini 9, validation 14; **not** Person A's 42 questions. Arms: **graph off**
(today's default: `GRAPH_ENABLED = False`, no links) versus **graph on** (concept candidates with the default
`graph_expand` arguments - no hardened parameters - plus the resolved-RELATED_TO link list), same rerank mode as
today. Report per set and pooled: R@1, R@3, R@5, MRR@5; per-question wins and losses at R@1 and at R@3; and the
5 incident pairs (`hybrid/benchmark/incident_link_check.json`) on versus off.

**Adoption rule: set `GRAPH_ENABLED = True` and `LINKS_ENABLED = True` only if no dev question is lost at R@1 or at
R@3 versus graph off. Otherwise both stay `False` and the losing questions are reported with their trace.**
The constants are committed separately from the measurement. The 5 incident pairs remain a mechanism check, not
generalisation evidence; the earlier hardening and link-decoupling verdicts were measured with the buggy merge.
