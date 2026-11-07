# E13 KG hardening - results

Run exactly as pre-declared in `docs/E13_kg_hardening_rule.md` (22 configurations, dev sets only: main 29, mini 9, validation 14; Person A's 42 questions were not used). Raw output: `knowledge_graph/output_hardening/hardening_results.json` (gitignored). Reproduce: `python knowledge_graph/evaluate_hardening.py` in the rag-api environment.

Baseline = same pipeline with the graph list disabled (vector + fusion + CrossEncoder, default rerank mode). Every configuration also uses the resolved-RELATED_TO sibling step and the gate's graph weight; only the concept-candidate profile of `graph_expand` differs. win = baseline missed the expected document in the top 3 and the configuration hits it; loss = the reverse.

## Baseline (graph disabled)

| set | R@1 | R@3 | R@5 | MRR@5 |
|---|---|---|---|---|
| main29 | 0.9310 | 1.0000 | 1.0000 | 0.9540 |
| mini9 | 0.4444 | 0.7778 | 0.7778 | 0.5926 |
| validation14 | 0.8571 | 0.9286 | 0.9286 | 0.8810 |
| pooled | 0.8269 | 0.9423 | 0.9423 | 0.8718 |

## All 22 configurations

| config | pooled W/L/net | main29 W/L | mini9 W/L | val14 W/L | pooled R@1 | R@3 | R@5 | MRR@5 | main29 R@3 | mini9 R@3 | val14 R@3 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V0 | 1/0/+1 | 0/0 | 0/0 | 1/0 | 0.7500 | 0.9615 | 0.9808 | 0.8446 | 1.0000 | 0.7778 | 1.0000 |
| V1 h=0.05 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8269 | 0.9231 | 0.9423 | 0.8670 | 1.0000 | 0.6667 | 0.9286 |
| V1 h=0.1 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8077 | 0.9231 | 0.9615 | 0.8603 | 1.0000 | 0.6667 | 0.9286 |
| V1 h=0.2 | 0/1/-1 | 0/1 | 0/0 | 0/0 | 0.7500 | 0.9231 | 0.9808 | 0.8362 | 0.9655 | 0.7778 | 0.9286 |
| V2 h=0.05 m=3 | 1/0/+1 | 0/0 | 0/0 | 1/0 | 0.8269 | 0.9615 | 0.9808 | 0.8885 | 1.0000 | 0.7778 | 1.0000 |
| V2 h=0.05 m=5 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8654 | 0.9231 | 0.9808 | 0.9054 | 1.0000 | 0.6667 | 0.9286 |
| V2 h=0.05 m=10 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8269 | 0.9231 | 0.9615 | 0.8708 | 1.0000 | 0.6667 | 0.9286 |
| V2 h=0.1 m=3 | 0/0/+0 | 0/0 | 0/0 | 0/0 | 0.8269 | 0.9423 | 0.9808 | 0.8869 | 1.0000 | 0.7778 | 0.9286 |
| V2 h=0.1 m=5 | 0/0/+0 | 0/0 | 0/0 | 0/0 | 0.8462 | 0.9423 | 0.9808 | 0.8965 | 1.0000 | 0.7778 | 0.9286 |
| V2 h=0.1 m=10 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.7885 | 0.9231 | 0.9808 | 0.8554 | 1.0000 | 0.6667 | 0.9286 |
| V2 h=0.2 m=3 | 0/0/+0 | 0/0 | 0/0 | 0/0 | 0.8462 | 0.9423 | 0.9808 | 0.8965 | 1.0000 | 0.7778 | 0.9286 |
| V2 h=0.2 m=5 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8269 | 0.9231 | 0.9808 | 0.8821 | 1.0000 | 0.6667 | 0.9286 |
| V2 h=0.2 m=10 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.7115 | 0.9231 | 0.9808 | 0.8170 | 1.0000 | 0.6667 | 0.9286 |
| V3 h=0.05 m=3 | 1/0/+1 | 0/0 | 0/0 | 1/0 | 0.8269 | 0.9615 | 0.9808 | 0.8885 | 1.0000 | 0.7778 | 1.0000 |
| V3 h=0.05 m=5 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8654 | 0.9231 | 0.9808 | 0.9054 | 1.0000 | 0.6667 | 0.9286 |
| V3 h=0.05 m=10 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8269 | 0.9231 | 0.9615 | 0.8708 | 1.0000 | 0.6667 | 0.9286 |
| V3 h=0.1 m=3 | 0/0/+0 | 0/0 | 0/0 | 0/0 | 0.8269 | 0.9423 | 0.9808 | 0.8869 | 1.0000 | 0.7778 | 0.9286 |
| V3 h=0.1 m=5 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8462 | 0.9231 | 0.9808 | 0.8949 | 1.0000 | 0.6667 | 0.9286 |
| V3 h=0.1 m=10 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.7885 | 0.9231 | 0.9615 | 0.8506 | 1.0000 | 0.6667 | 0.9286 |
| V3 h=0.2 m=3 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8462 | 0.9231 | 0.9808 | 0.8949 | 1.0000 | 0.6667 | 0.9286 |
| V3 h=0.2 m=5 | 0/1/-1 | 0/0 | 0/1 | 0/0 | 0.8269 | 0.9231 | 0.9808 | 0.8821 | 1.0000 | 0.6667 | 0.9286 |
| V3 h=0.2 m=10 | 0/0/+0 | 0/0 | 0/0 | 0/0 | 0.7115 | 0.9423 | 0.9808 | 0.8218 | 1.0000 | 0.7778 | 0.9286 |

## Selected cell and adoption-rule verdict

Selected (highest pooled wins - losses; ties: smaller max_documents, then larger hub_fraction): **V2 h=0.05 m=3**, pooled wins 1, losses 0, net +1; smallest single-set net +0.

Adoption rule: pooled net >= +2 AND pooled losses <= 2 AND no single dev set net < -1.

**Verdict: FAIL.** Negative result: the graph stays OFF by default.

### Per-question wins and losses of the selected cell

- [validation14] **WIN** My KYC is showing pending - will my number get disconnected, and what do I need to do?  expected=['FAQ_C17_034', 'KB_C17_kyc_reverification']  baseline top3=['TRX_007', 'FAQ_C22_044', 'SOP_C22_ACTIVATION_DELAY']  config top3=['TRX_007', 'FAQ_C22_044', 'FAQ_C17_034']

## Hub audit (each document as a single seed, graph_expand limit 20)

Hub = concept in more than 10% of documents. `share_only_hub_concepts` = share of candidates whose shared concepts are all hubs. Same-category precision is a rough proxy for relevance (mean over seeds that have candidates).

V3 best = V3 h=0.05 m=3.

| profile | candidates | share sharing only hubs | same-category p@5 | p@20 |
|---|---|---|---|---|
| V0 | 2393 | 0.7238 | 0.3766 | 0.2692 |
| V1 h=0.10 | 948 | 0.0 | 0.6786 | 0.6232 |
| V3 best | 321 | 0.0 | 0.8512 | 0.8512 |

Reference simulation from the task brief: 72% (1732 of 2393) of V0 candidates share only hubs; same-category p@5 was 0.38 (V0), 0.68 (hub cut), 0.72 (specific labels only).

## Reading the table (added by hand after the run)

- **Verdict FAIL, stated plainly: this is a negative result.** The best cell reaches pooled net +1 (one win, no loss), below the pre-declared
  +2; no cell reaches +2. Under the pre-declared rule the graph stays OFF by default.
- **The measurable defect is real and fixed in isolation; the downstream benefit is not shown.** The hub audit reproduces the simulation
  (72.4% of legacy candidates share only hub concepts; same-category p@5 0.38 -> 0.68 with the hub cut -> 0.85 for the best V3 cell), but at the
  document level, after fusion and the CrossEncoder, the 52 dev questions barely move: legacy V0 itself is net +1, and every cell is within
  one question of the graph-off baseline.
- **Resolution is one question.** All differences are 0 or +-1 question out of 52; the "selected" cell and V0 differ by a single question
  (the KYC question, FAQ_C17_034). Do not read the ordering of cells as a ranking.
- **Tie:** `V2 h=0.05 m=3` and `V3 h=0.05 m=3` have identical outcomes (net +1); the first in grid order is reported as selected.
- The dev sets all pass through the same rerank (default `rrf_blend`), which can demote graph candidates (see `docs/E13_Hybrid_Fusion_Roadmap.md`
  Section 8); this evaluation cannot separate a weak graph signal from the reranker undoing it.
