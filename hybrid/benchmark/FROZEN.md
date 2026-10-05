# route_benchmark.json is FROZEN

- **Frozen at commit:** `4594022` ("E13 Phase 6b: frozen route benchmark (24 Q, SQL-derived ground truth)")
- **Authored before any router or adapter code exists.** It is the held-out set for E13 Phases 7-10.
- **Rule:** no edits to `route_benchmark.json` (or to the questions in `build_route_benchmark.py`) after this
  point, except a documented amendment appended below that lists what changed and why. Do not retune a
  router/adapter and then edit the benchmark to match; do not regenerate it with different questions.
- Regenerating with the unchanged script reproduces the file byte-for-byte; the build asserts the SQL-derived
  anchor facts and `hybrid/tests/test_route_benchmark.py` re-derives every expected value from the database.

## Known property worth knowing before you score against it

RB_S06 is a deliberate data trap: invoice 6740 is recorded `Unpaid` although SUCCESS payments already total
its full amount (581.65). Its expected values contain both facts.

## Amendments

None.
