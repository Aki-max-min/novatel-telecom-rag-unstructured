# Summary for Person B: your hardened graph inside our RAG pipeline

**Short answer: neutral.** Your V1 profile (`hub_fraction=0.05, specificity=True, max_documents=3`) changes what the graph adds on 23 of our 42 questions, improves every retrieval metric, and leaves answer correctness unchanged under all three scoring rules (strict, partial credit, lenient). Adding the repaired RELATED_TO links on top (our `use_related_links=True` path; 47 of 84 links resolve) is neutral to slightly positive, not significant. Neither closes the gap between our semantic-layer arms and the plain RAG baseline B2; that gap belongs to the router and the multi-hop questions, not to the graph.

Setup: our 42-question set, 3 runs per arm, same model / prompts / judge / seed as our v3 report, merged from your branch tip `700a5dd`. B2 = baseline, no router, no graph. C_V0 = router + semantic layer with the legacy `graph_expand`. C_V1 = C_V0 with your V1 keyword arguments. C_V1_links = C_V1 + RELATED_TO hop.

| metric (mean of 3 runs) | B2 | C_V0 | C_V1 | C_V1_links |
|---|---|---|---|---|
| correctness, partial credit, all 42 | 84.1% | 66.7% | 65.9% | 68.7% |
| correctness, strict (fully correct in a majority of runs) | 73.8% | 59.5% | 57.1% | 59.5% |
| correctness, lenient (score >= 1 in a majority of runs) | 95.2% | 73.8% | 73.8% | 76.2% |
| groundedness | 95.6% | 90.4% | 93.8% | 95.2% |
| hallucination vs reference evidence | 36.5% | 48.4% | 51.6% | 47.6% |
| R@1 / MRR@10 (25 document questions) | 0.760 / 0.837 | 0.360 / 0.516 | 0.440 / 0.580 | 0.600 / 0.697 |
| chunks added by the graph (run 1) / of which gold | n/a | 85 / 7 | 55 / 13 | 65 / 19 |
| gold document at rank 1 (25 document questions) | 19 | 9 | 11 | 15 |
| gold displaced from the top 10 vs B2 | n/a | 1 (RW_017) | 0 | 0 |
| prompt tokens, median | 1526 | 1349 | 1200 | 1200 |

Paired at question level (42 pairs; wins / losses / ties, exact McNemar p, paired bootstrap 95% CI in points):

| comparison | strict | partial credit | lenient |
|---|---|---|---|
| C_V1 vs C_V0 | 2 / 3 / 37, p=1.00, CI [-13.5, +7.9] | 4 / 4 / 34, p=1.00, CI [-8.3, +6.3] | 1 / 1 / 40, p=1.00, CI [-6.3, +7.9] |
| C_V1_links vs C_V1 | 2 / 1 / 39, p=1.00, CI [-4.8, +11.9] | 4 / 2 / 36, p=0.69, CI [-2.8, +9.1] | 1 / 0 / 41, p=1.00, CI [-1.6, +7.9] |
| C_V1_links vs B2 | 3 / 9 / 30, p=0.15, CI [-28.6, +2.4] | 4 / 12 / 26, p=0.08, CI [-27.4, -4.8] | 0 / 8 / 34, p=0.008, CI [-30.2, -7.1] |

What the hardening did, mechanically: the legacy layer added 44 hub-only documents (TRX / EML / TRN transcripts reached through generic concepts) and pushed the gold document out of the top 10 on RW_017. V1 adds none of those, caps at 3 documents per question, and the share of added chunks that are gold rises from 7 of 85 to 13 of 55. That shows in retrieval (R@1 0.36 to 0.44) but not in answers: V1 wins Q08 and MH_RB_B02 and loses Q04 (the model cites the added FAQ_C27_053 instead of the gold), Q25 (cites the added KB_C25 chunk, judged partial) and MH_RB_B01 (structured rows missing in that arm's runs, a hybrid-route effect we cannot pin on the graph). The links hop puts a RELATED_TO document in the prompt on 6 questions and turns MH02 and MH03 (incident -> RCA pairs) from 0 to 2 in every run; it loses MH_RB_B02 (2 to 1). That is the only place the links visibly helped. On the 14 questions where the graph fires at all (gate weight > 0), partial-credit correctness is B2 81.0%, C_V0 46.4%, C_V1 44.0%, C_V1_links 52.4%.

Why every C arm is 15-18 points below B2 whatever the graph: 12 of the roughly 50 wrong answers per C arm are the router sending the question to the wrong source or out of scope (identical across the three C arms and identical to v3), and the multi-hop / cross questions lose most. The graph cannot fix those.

Reproducibility: our B2 on your branch is 84.1% vs 82.9% in v3 (4 wins / 3 losses, p=1.0; your parser fixes raise database-row coverage from 89.2% to 93.8%). C_V0 is 66.7% vs v3 C 67.5% (3 / 2, p=1.0) with identical retrieval metrics and identical routes, so the legacy profile reproduces.

Caveat: 42 questions, 3 runs, a local 7B judge. Differences of 1-4 questions are inside noise. We are not claiming the hardening hurts; we cannot see it helping answer quality in this pipeline. Full tables: `comparison_table.md`, `graph_diagnostics.md`, `per_question_scores.csv`, `error_table.csv` in this folder.
