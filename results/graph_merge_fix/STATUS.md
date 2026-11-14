# STATUS: graph merge fix measurement

Branch `exp/kg-hardening-eval`; written 2026-11-11 (UTC). Nothing pushed, no history rewritten.

## What ran

| step | result |
|---|---|
| reproduction of Person B's count (v3 docgraph run 1) | 17 document questions with graph weight > 0; 44 of 44 documents above the gold are graph neighbours; gold at rank 1 19/25 (B2) vs 10/25 (docgraph); RW_017, MH02, MH04, MH05, MH_RB_B05 fell to lost / 5 / 6 / 7 / lost (`01_reproduce_personB_count.txt`) |
| tests before the change | `integration/tests/test_semantic_merge_order.py`: 4 of 7 failed on the old merge (`02_tests_before_fix.log`) |
| fix | commit `d7b8e1c`: `_semantic_merge` orders the pool by CrossEncoder score alone (tie-break chunk id); weighted-RRF bonus block deleted; trace fields kept; graph_weight only an on/off switch. Person B's optional RELATED_TO-at-weight-0 change NOT adopted (gate contract; own measurement needed) |
| tests after | 19 passed (7 new + 12 existing semantic/budget tests), 0 failed (`03_tests_after_fix.log`) |
| pre-declaration | `PRE_DECLARATION.md`, committed `afcfa8f` before the smoke test |
| smoke | plain search == stored B2 run-1 chunk lists on 42/42 (B2 reuse is sound); GF differs from plain on 21/42, 77 added chunks; GFL differs from GF on 1/42; verdict proceed |
| generation | GF, GFL x 42 x 3 = 252 records, 0 failures, 0 latency records flagged, 1568 s (11:04-11:30 UTC); manifest at `afbbe8d`, clean tree; reused-arm check: only `integration/rag/pipeline.py` and the new test file differ from the B2 commit, graph.json identical |
| scoring | 252/252, 0 failures (11:31-13:00 UTC); 23 new judge calls, 763 cache hits of which 690 from the v3 / KG-hardening caches |
| report | `metrics.json`, `values.json`, `comparison_table.md`, `paired_comparisons.md`, `graph_diagnostics.md/.json`, `graph_cases.md/.json`, `error_table.csv`, `per_question_scores.csv` |

## Oddities (reported, not worked around)

1. **Battery**: generation started on battery (60% at start, sleep-after 0 on AC and DC) with the explicit `--allow-battery` override because the
   stage is short and resumable; charge fell to 43% / 29 min estimated at 80/252 and the user was warned; the machine was on AC (47%) when
   generation finished and scoring started. No record was flagged as a gap or slow.
2. **GF latency**: median 7.0 s (p95 15.5 s) vs GFL 4.6 s and B2 3.6 s. GF ran first, partly while the battery was draining (likely CPU/GPU
   throttling on battery, inference); retrieval is identical across runs and no record exceeded the 120 s rule, so correctness is unaffected,
   but GF's latency figures should not be compared with the other arms.
3. **Scoring speed**: ~55 s per record vs 11 s in the KG-hardening run, with the judge almost entirely cache hits; the time went into the NLI
   citation verifier on CPU (and, for the first 20 minutes, the diagnostics scripts I ran concurrently). Results are unaffected.
4. **Judge cache**: 690 of 763 hits came from earlier caches because B2-identical prompts (gold at the same rank, same blocks) recur; 23 new calls.
5. The fix changed `integration/rag/pipeline.py`, so the pre-declared code state of the final ablation (`results/final_ablation/`, HEAD 6956902)
   no longer holds for graph arms; per the user's decision the final-ablation long run and a C-arm re-run were NOT started (see
   `results/final_ablation/STATUS.md`).

## Not done

* No tuning; one run of the protocol. The optional "RELATED_TO neighbours at graph_weight 0.0" change is a follow-up, not measured.
* The v3, v4 and KG-hardening graph arms (docgraph, C, C_V0, C_V1, C_V1_links) were NOT re-scored or re-run: they stand as measured with the old merge.
