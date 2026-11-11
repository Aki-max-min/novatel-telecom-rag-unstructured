# Summary: the graph merge fix, measured once (B2 vs B2 + fixed graph, router OFF)

**Verified.** Person B's diagnosis holds: in the v3 docgraph arm all 44 documents that outranked a gold document were graph neighbours pushed up by
the weighted-RRF bonus, and gold at rank 1 fell from 19/25 (B2) to 10/25. After the fix (graph neighbours only join the pool; CrossEncoder order
decides) the graph never moves a gold document down: on the 25 document questions the gold rank vs B2 is 1 better / 24 same / 0 worse / 0 lost
for both GF and GFL, gold at rank 1 stays 19/25, and no regression case exists for the CrossEncoder-score check to explain (`graph_cases.md`).

| metric (3 runs, 42 questions) | B2 | GF (fixed merge, legacy graph_expand) | GFL (+ RELATED_TO hop) |
|---|---|---|---|
| correctness, partial credit | 84.1% | 83.3% | 83.3% |
| correctness, strict | 73.8% | 71.4% | 71.4% |
| correctness, lenient | 95.2% | 95.2% | 95.2% |
| R@1 / R@3 / R@5 / R@10 | 0.760 / 0.920 / 0.960 / 1.000 | 0.760 / 0.960 / 1.000 / 1.000 | 0.760 / 0.960 / 1.000 / 1.000 |
| MRR@10 | 0.837 | 0.843 | 0.843 |
| groundedness / halluc. vs context | 95.6% / 4.0% | 95.6% / 4.0% | 96.4% / 2.4% |
| chunks added (run 1) / of which gold / reached the prompt | n/a | 77 / 7 / 12 | 77 / 7 / 13 |
| gold rank vs B2 better / same / worse / lost | n/a | 1 / 24 / 0 / 0 | 1 / 24 / 0 / 0 |

Paired (42 pairs): GF vs B2 strict 0 wins / 1 loss / 41 ties, partial 0 / 1 / 41, lenient 0 / 0 / 42; GFL vs B2 strict 0 / 1 / 41, partial 1 / 1 / 40,
lenient 0 / 0 / 42; GFL vs GF partial 1 / 1 / 40, otherwise all ties. Every p = 1.0, every CI straddles or touches zero. The one loss is MH_RB_B05
(B2 2/2/2, GF 2/1/1, GFL 1/1/1): gold at rank 1 in all arms, a hub-only transcript chunk (TRX_003) reached the prompt, the model answered
partially; error cause "model" by the v3 rule. The one GFL win is Q20 (B2 1/2/2, GFL 2/2/2), same prompt documents, answer noise.

**Reading.** With the merge fixed, the legacy graph (and the link hop) is neutral on answers and slightly positive on retrieval depth (R@3 and
R@5 up, the top-1 unchanged), at the cost of a few extra chunks in the prompt (median prompt tokens 1,533 vs 1,526). The large retrieval losses of
every earlier graph arm were the merge, not the graph. Not safe to claim on 42 questions: that the graph helps answers; one discordant question
is noise.

**Scope note (verified).** Every earlier graph result was generated with the old merge: v3 docgraph and C, the v4 report rows built on them, and
the KG-hardening arms C_V0, C_V1 and C_V1_links (`results/kg_hardening_eval/`), which this report still carries as reused arms. Those numbers
describe the merge bug at least as much as the graph or the hardening; they were not re-run (user decision 2026-11-11). Person B's hardening and
link verdicts were measured in their own `hybrid/` pipeline, which has its own fusion; whether that fusion has the same property was not checked here.
