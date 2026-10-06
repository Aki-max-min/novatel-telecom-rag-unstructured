# E13 Phase 8e - acceptance and revert rule (declared BEFORE any code change)

The clause-level router is accepted only if, on the frozen benchmark, route accuracy >= 23/24, outcome accuracy is 24/24,
leakage is 0, and no question that was correct under amended-2 becomes incorrect. If any condition fails, revert the router
change commits with `git revert` (keep the log entry explaining why) and stop. This is the LAST router change before the
blind set, whichever way it goes.

## Reference points (fixed now, from the committed result files)

- Frozen benchmark: `hybrid/benchmark/route_benchmark.json`.
- Amended-2 run (the comparison for "no question that was correct becomes incorrect"):
  `hybrid/benchmark/amended2_run_phase8d.json` (commit 96de8e0) - route 22/24, outcome 24/24, structured fact recall 26/30,
  leakage 0. Its misses are RB_B02 and RB_B03 (route) and RB_B01 (document hit@3).
- "Correct" for a question means what the run files already measure: route matches, outcome matches, every expected structured
  fact is returned, and, for document items, the expected-document hit@3 / hit@5 result recorded in that file.

## What a failure means

Any single failed condition triggers the revert, including a regression on one previously-correct question even if the headline
accuracy improves. The revert keeps the log entry (what was tried, which condition failed, the numbers). No retry or tweak follows;
the router stays as it was before this phase.
