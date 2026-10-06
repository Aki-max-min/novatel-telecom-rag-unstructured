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

---

## Outcome (appended after the run; the rule above was not changed)

| Variant | main R@1 / R@3 / R@5 / MRR@5 | mini R@1 / R@3 / R@5 / MRR@5 | macro-MRR@5 | vetoed | validation hit@3 / hit@5 / MRR@5 (14) |
|---|---|---|---|---|---|
| V0 override | 0.9310 / 1.0000 / 1.0000 / 0.9598 | 0.2222 / 0.6667 / 0.8889 / 0.4759 | 0.7178 | no | 13 / 13 / 0.8810 |
| V1 blend w=1.0 | 0.8276 / 1.0000 / 1.0000 / 0.9080 | 0.5556 / 0.7778 / 0.8889 / 0.6574 | **0.7827** | no | 13 / 14 / 0.8238 |
| V2 blend w=0.5 | 0.7241 / 0.9655 / 1.0000 / 0.8517 | 0.5556 / 0.8889 / 0.8889 / 0.6667 | 0.7592 | no | 14 / 14 / 0.7738 |
| V3 protect_graph | identical to V0 on every set | | 0.7178 | no | 13 / 13 / 0.8810 |

**Winner by rule: V1. Validation check: pass** (V1 hit@3 = V0 hit@3 = 13/14, a drop of 0 items). **Adopted: V1** -
`DEFAULT_RERANK_MODE` in `hybrid/rerank.py` is now `rrf_blend` with weight 1.0.

Things the numbers do not say, stated plainly:

- V1 is not a free win. On the main benchmark it loses Recall@1 (0.9310 -> 0.8276) and MRR@5 (0.9598 -> 0.9080); on
  the validation set its MRR@5 is lower than V0's (0.8238 vs 0.8810) even though hit@5 is higher. The rule picks it
  because the mini-benchmark gain (MRR@5 0.4759 -> 0.6574) outweighs the main-benchmark loss in the macro average,
  and the mini set has only 9 questions.
- V3 changed nothing: on all 52 questions the best graph-only candidate in the fusion top 5 was either absent or
  already in the final top 5.
- Both selection sets were already used for tuning (see above), so these selection numbers are optimistic;
  the 14-question validation set is small (one question = 7 points of hit@).

Implementation note: the first execution of the script marked V2 as vetoed. V2's main Recall@3 is 0.9655 vs 1.0000,
a drop of exactly one question (1/29), which the rule does NOT veto ("more than 1/29"); the script had compared
4-decimal rounded values without allowing for the rounding. The comparison was corrected (tolerance 1e-4) and the script re-run:
every metric was identical to the first execution, only V2's veto flag changed, and the winner was V1 both times.

---

## Post-outcome addendum (written after seeing results)

The rule text and the outcome section above are unchanged. This addendum was written after the numbers were known, and says so.

**Pooled view over the 38 selection questions (29 main + 9 mini), recomputed from the stored rankings in
`hybrid/evaluation_results_rerank_variants.json`:**

| Variant | Top-1 hits | Pooled MRR@5 |
|---|---|---|
| V0 override | 29 / 38 | 0.8452 |
| V1 blend w=1.0 | 29 / 38 | 0.8487 |
| V2 blend w=0.5 | 26 / 38 | 0.8079 |
| V3 protect_graph | 29 / 38 | 0.8452 |

On the validation set V1's MRR@5 is 0.8238 against V0's 0.8810, with equal hit@3 (13/14) and higher hit@5 (14/14 vs 13/14).
(V1's pooled MRR@5 is 0.8487 when recomputed; an earlier hand-quoted figure of 0.8486 differs by rounding only.)

**What this shows.** Pooled over all 38 questions, V0 and V1 are indistinguishable on top-1 hits (29 each) and on MRR@5
(0.8452 vs 0.8487, a difference of 0.0035). The macro-average in the rule gives the 9-question set the same weight as
the 29-question set, so one question on the mini set moves the macro score about three times as much as one on the main set.
That is a weakness of the rule as written. V1 was selected by that rule and its outcome is recorded as is; the rule is not
being rewritten.

**V3.** V3 was identical to V0 because it protects a graph-only candidate against eviction from the top 5, but the observed
mechanism is demotion *within* the top 5 (the CrossEncoder reorders candidates that are already present), which V3 does not address.

**Decision on the shipping default.** V1 remains the current default only because the rule selected it. The shipping default
will be decided on a blind set, using only that set's unstructured and both items: **adopt V1 only if its pooled MRR@5 beats
V0's by at least 0.02, otherwise V0.** The blind set has not been written yet; nothing in this paragraph has been tested.
The default is controlled by the single constant `DEFAULT_RERANK_MODE` in `hybrid/rerank.py` ("rrf_blend" = V1, "override" = V0).
