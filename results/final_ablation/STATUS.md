# STATUS: final component ablation (NOT RUN; analysis parts complete)

Branch `exp/kg-hardening-eval`; written 2026-11-11 (UTC).

## Done (committed)

| item | file | commit |
|---|---|---|
| pre-declaration (arms A, B, R, O, G0, G1, G1L generated; B2, C_V0, C_V1, C_V1_links reused), written before any run | `PRE_DECLARATION.md` | `1dd520f` |
| arm -> exact settings mapping, printed from the harness | `mapping_table.md` | `1dd520f` |
| harness (`eval/final_ablation/harness_fa.py`, `fa_generate.py`, `fa_score.py`, `fa_report.py`, `fa_graph_cases.py`) | | `1dd520f` .. `2db66c3` |
| health check, runtime estimate (82 min generation + 163 min scoring), smoke test passed (labels OK; G1 differs from G0 on 22/42; links on 14/42; O rewrites 23/42 queries) | `health.json`, `time_estimate.json`, `smoke_test.json` | `230338e` |
| Part 4 error-label reconciliation: rule identical to v3 (`dc481b6`), both tables reproduce exactly; v3 C vs C_V0 differ on 12 answers (MH12/MH13 parser; RW_001/MH_RB_B04 answer noise) | `error_label_reconciliation.md/.json` | `dc36bde` |
| Part 5a abstention composition: 12 per C arm = S15 x3 (router, correct) + MH01/MH04/MH05 x3 (structured source empty, unnecessary) | `abstention_composition.md/.json` | `dc36bde` |
| Part 5b failing tests: 6 failures, all from Person B's structured-side changes (parser `2f365ea`/`478256f`, retriever `794662c`); nothing fixed | `failing_tests.md`, `failing_tests_pytest.log` | `dc36bde` |
| Part 5c structured KG wiring plan (plan only) | `docs/STRUCTURED_KG_WIRING_PLAN.md` | `afcfa8f` |

## Not run (user decision 2026-11-11)

The generation of A, B, R, O, G0, G1, G1L was never started. Reason: after the pre-declaration, Person B's graph-merge fix was applied to
`integration/rag/pipeline.py` (commit `d7b8e1c`). The pre-declared single code state (HEAD `6956902`, old merge) therefore no longer exists for
the graph arms, and the reused C arms (`results/kg_hardening_eval/`) were generated with the old merge. The user decided not to start the
long run and not to re-run the C arms now. The harness refuses to run this experiment at HEAD because `integration/rag/pipeline.py` differs from
the reused arms' commit (`verify_reused_arms`), which is the intended safeguard.

If the ablation is run later it needs a new pre-declaration on the fixed code, the C arms re-generated (3 x 126 answers, ~35 min + scoring) so
that every arm shares one code state, and the old-merge results kept as a separate, labelled column.

## Not produced

`raw_answers.jsonl`, `scored_answers.jsonl`, `metrics.json`, `values.json`, `comparison_table.md`, `ablation_table.md`, `paired_comparisons.md`,
`graph_diagnostics.md`, `error_table.csv`, `per_question_scores.csv`, `run_manifest.json`, `SUMMARY.md` for this experiment do not exist. The
measured graph-fix results are in `results/graph_merge_fix/`.
