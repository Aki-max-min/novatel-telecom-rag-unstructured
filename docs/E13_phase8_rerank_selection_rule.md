# E13 Phase 8b - rerank selection rule (declared BEFORE any variant is run)

Phase 5 found that the CrossEncoder, which fully overrides the fusion order, undid the graph's contribution on
the graph-dependent mini-benchmark (gate + fusion alone: Recall@1 0.4444 / Recall@5 1.0; after the override
rerank: 0.2222 / 0.8889) while giving the whole gain on the main benchmark. This document fixes, in advance,
which variants are compared, on which data, and the mechanical rule that picks one.

## Variants - these four and no others

Notation: the candidate pool is the output of `fuse_and_select`, capped at `max_pool` = 20 by fusion score.
`rank_fusion` = 1-indexed position in that pool (fusion order). `rank_rerank` = 1-indexed position of the
candidate when the pool is sorted by CrossEncoder score. `top_k` = 5.

| Variant | Definition |
|---|---|
| **V0 override** | Current behaviour. Final order = CrossEncoder score, descending. |
| **V1 rrf_blend, w=1.0** | score = 1/(60 + rank_fusion) + w/(60 + rank_rerank) with w = 1.0; final order = score, descending. |
| **V2 rrf_blend, w=0.5** | Same formula with w = 0.5. |
| **V3 protect_graph** | The final top_k reserves 1 slot for the best graph-only-sourced candidate (`fusion_sources == ["graph"]`) that sits within the fusion top 5 (`rank_fusion` <= 5); "best" = lowest `rank_fusion`. The remaining top_k - 1 slots are filled by rerank order from the other candidates. The final set is then ordered by CrossEncoder score. If no such candidate exists, or it is already in the V0 top_k, V3 equals V0. |

(60 is the RRF constant already used throughout hybrid/.) Blended scores tie-break on `rank_rerank`, then `rank_fusion`.

## Selection sets

- **Main benchmark**, 29 questions (`ingestion/retrieval_benchmark.json`).
- **Graph-dependent mini-benchmark**, 9 questions (`knowledge_graph/graph_benchmark.json`).

Both sets were already seen, and used for tuning and diagnosis, in earlier phases (the fusion weights, the
gate and the Phase 5 analysis all looked at them). Selection on them is therefore optimistic; this is
stated up front and the validation set below exists for that reason.

Metrics are the ones used since Phase 5 (`knowledge_graph/evaluate_graph_rag.py`): Recall@1/3/5 (any
expected document in the top k) and MRR@5, over document ids. All variants are evaluated with the gate and
fusion **as of Phase 8a** (so V0 here is V0 under the Phase 8a gate; the Phase 5 rows are compared separately
in Phase 8c).

## Selection rule (mechanical)

1. For each variant compute macro-average MRR@5 = (MRR@5 on main + MRR@5 on mini) / 2.
2. **Veto:** reject any variant whose main Recall@3 or main Recall@5 is below V0's by more than 1/29
   (i.e. by more than one question).
3. Winner = the non-vetoed variant with the highest macro-average MRR@5 (V0 is never vetoed).
4. **Ties** (macro-MRR@5 equal to four decimals) go to the variant closest to V0, in this order:
   V0, V3, V1, V2.

## Validation set

The **14 unstructured + both items of the frozen route benchmark** (8 unstructured + 6 both). Rerank
variants were not tuned on them. The documents channel (real vector + graph candidates -> gate weight ->
fuse -> dedup -> rerank variant) is evaluated for all 14 regardless of what the router decides, so the
check isolates the rerank variant. Metrics: hit@3, hit@5 (any expected document in the top k) and MRR@5.

**Adopt the rule's winner only if its validation hit@3 is not lower than V0's by 1 or more items.**
Otherwise keep V0 and report why. If V0 is the winner, V0 stays.

## Procedure and commitments

- `controlled_rerank(..., mode=...)` is added with V0 as the default; the default changes only if this rule
  adopts another variant.
- `hybrid/evaluate_rerank_variants.py` is run **once**; all four variants are printed on all three sets.
- The rule is applied as written. It is not changed after the numbers are seen; if V0 wins, or the
  validation check vetoes the winner, that is the result.
