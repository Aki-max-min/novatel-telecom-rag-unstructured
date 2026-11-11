# E13 KG fixes - rules (pre-declared) and results

Fixes the in-plan gaps of the read-only audit (`docs/E13_kg_audit.md`, on branch `person-b/kg-audit`). Branch `person-b/kg-fixes`, started from
`person-b/kg-hardening` at `4956b37`. Each step: tests first (committed), then the change, then a separate commit. No new retrieval layer.
**This section is committed before any experiment is run; results are appended below it and the rules are not edited afterwards.**

## Common measurement protocol (steps 2, 4, 5, 6)

- Dev sets: the **52** questions already used throughout the project - main 29, mini 9, validation 14 (the same sets as the hardening, link-decoupling and
  fusion-fix evaluations). **Person A's 42 questions are not used.**
- Metric per question: whether an expected document is in the final top 1 / top 3 / top 5 (document level). A **loss** = the baseline arm hits and the
  candidate arm does not; a **gain** = the reverse. Also reported per set and pooled: R@1, R@3, R@5, MRR@5, and the 5 incident pairs
  (`hybrid/benchmark/incident_link_check.json`: both documents of the pair in the final top 5).
- Same pipeline, gate and CrossEncoder for both arms (CrossEncoder scores cached and shared); only the named setting differs.
- The incident check is a mechanism check on five pairs, not generalisation evidence.

## Step 2 rule - one link mechanism

`run_hybrid_query` calls `build_candidates(use_related_links=False)`; only the separate link list from `link_candidates_for` stays.
Arms: before = `use_related_links=True` (today), after = `use_related_links=False`, graph and links on in both, default rerank mode.
**Keep the change only if no dev question loses its expected document at R@1, R@3 or R@5; otherwise revert and report the losers.**

## Step 3 acceptance (no experiment: retrieval must not move)

Concept metadata joins the graph build and `GraphIndex`; `hybrid/context.py` stops dropping `concept`. Accepted only if: the top 5 of all 52 dev questions
is **identical** before and after; the extractive answer text for the anchor customers is identical; Person A's `_read_related_edges` and the 5 incident
pairs still read the new `graph.json` unchanged; two graph builds are byte-identical.

## Step 4 rule - category-tag leak

Arm B excludes tags matching `^c\d\d$` from the bridge labels of `graph_expand` (option `exclude_category_tags`); arm A = current.
**Keep only if no dev question is lost at R@1, R@3 or R@5 AND at least one question gains at R@3 or R@5; otherwise leave unchanged and report.**

## Step 5 rule - fair blend

Graph and links on. Arm A = current `rrf_blend` w=1.0; arm B = CrossEncoder-only order for the pool (`mode="override"`, the design Person A uses).
**Adopt arm B only if no question is lost at R@1, R@3 or R@5, at least one question gains (at any of the three), and the 5 incident pairs are not worse; otherwise keep A.**
Also reported: the 14 expected documents that are not vector hits (how many reach the top 5 now; the audit measured 0) and the 19 CrossEncoder-top-5 appended
documents the blend pushed out (where they land in arm B). Note: the rerank default was previously chosen by a pre-declared rule and the blind-run protocol
(`docs/E13_blind_run_protocol.md`) reserves the V0-vs-V1 decision for the blind set; if arm B is adopted here that is a documented deviation, recorded in the protocol file.

## Step 6 rule - hardened graph profile

Run **after** step 5 (and step 4), in their accepted state. Arm A = legacy `graph_expand`; arm B = the hardened cell `hub_fraction=0.05, specificity=True,
max_documents=3` passed through `graph_kwargs` (`max_documents=3` caps the candidate list at 3 documents; there is no per-concept cap parameter, so this is the
existing `V2 h=0.05 m=3` cell). **Same rule as step 5**: adopt only if no question is lost at R@1/R@3/R@5, at least one gains, and the 5 incident pairs are not worse.

## What is NOT shown (stated up front)

The dev sets are the sets everything was developed on; a "no loss" verdict here is not generalisation evidence and differences below one question cannot be
resolved. Person A's 42 questions remain the unbiased test and must not be used for tuning.

---

# Results (appended 2026-11-11; the rules above were committed first, in `9bd2b21`, and are unchanged)

All experiments: 52 dev questions, graph and links on, same CrossEncoder scores in both arms. Raw output: `knowledge_graph/output_hardening/fixes_<step>.json` (gitignored); command `python hybrid/evaluate_fixes.py stepN` in the rag-api environment.

| Step | Change | Result | Verdict |
|---|---|---|---|
| 1 | Graceful degradation | 22 new tests (one per audit table-C scenario); fresh clone without `graph.json`: 316 passed, 17 skipped, 0 failed | done |
| 2 | One link mechanism (`use_related_links=False`) | pooled R@1 0.8269, R@3 0.9423, R@5 0.9615, MRR@5 0.8756 in both arms; 0 losses, 0 gains | KEEP |
| 3 | Concept metadata in the graph | graph 337 -> 360 nodes, 1636 -> 1669 edges; top 5 of all 52 dev questions and the anchor answers identical; builds byte-identical | accepted (no retrieval change) |
| 4 | Exclude category-code tags | 0 losses, 0 gains at R@1/R@3/R@5; incident 3/5 vs 3/5 | LEAVE UNCHANGED (option kept, default off) |
| 5 | Blend: `rrf_blend` vs CrossEncoder-only | arm B: 3 losses at R@1, 1 at R@3, 0 at R@5; 1 gain at R@1 | KEEP A (rule failed: losses) |
| 6 | Hardened graph profile | identical on every metric; 0 losses, 0 gains; incident 3/5 vs 3/5 | KEEP A (rule failed: no gain) |

## Step 1 - graceful degradation

Nothing raises on a missing asset any more. `get_graph_index_safe()` returns `(index, reason)`; the graph is loaded lazily and only when `GRAPH_ENABLED` or `LINKS_ENABLED`. Trace notes: `graph unavailable: <reason>`, `vector retrieval unavailable: <reason>`; the structured side gives `structured_executed=False` plus `structured_note` when the database is missing, and documents still run. The answer layer says "I can't answer from the documents because document retrieval is unavailable right now." (or the account-lookup equivalent) and suppresses absence sentences when the structured side is down, so nothing is invented. The loader's error text and the `setup_check` command are unchanged. Tests: `hybrid/tests/test_graceful_degradation.py` (22).

The 7 end-to-end tests that failed in a fresh clone (no `graph.json`) now run: with the graph missing they receive documents plus a trace note, so their assertions on facts, documents and outcomes hold. Fresh clone result: 316 passed, 17 skipped (models or graph assets absent, each skip with its reason), 0 failed.

## Step 2 - one link mechanism

Rule: keep only if no dev question loses its expected document at R@1/R@3/R@5. Measured: identical top 5 for every question, so the duplicate path (top-5-seed neighbours placed first in the graph list and again in the link list) is removed with no cost. Linked documents now enter once, with `fusion_sources == ["links"]`.

## Step 3 - concept metadata (structured side joins by metadata only)

23 `Concept` nodes carry a `tables` property (names of the 28 structured tables, each mapped once) and 33 `EXPRESSES_CONCEPT` edges (22 from Categories, 11 from Services) link documents' categories and services to concepts. The join key is the concept **name**, not the C-code (only 8 of 28 crosswalk rows agree on a code). Concepts sharing one category (Plan Catalogue/Subscription, Payments/Recharge, Network Coverage/Network Outages) stay separate nodes; the `GraphIndex` accessors `documents_of_concept`, `categories_of_concept`, `tables_of_concept`, `concepts_of_category` and `concept_groups` return the document groups deduplicated. `hybrid/context.py` no longer drops `concept` (facts carry it; `Context.concepts`; trace key `fact_concepts`). No rows or values enter the graph. Checks: the replica of Person A's `_read_related_edges` still reads 84 RELATED_TO edges (47 between resolved documents) and the five incident pairs in both directions; two builds are byte-identical; `graph_expand` and `related_neighbours` return the same with or without the concept layer.

## Step 4 - category-tag leak

Zero change at any cut-off, so by the rule the default stays. The `exclude_category_tags` option on `graph_expand` remains available (default False).

## Step 5 - fair blend

| set | A R@1 | A R@3 | A R@5 | A MRR@5 | B R@1 | B R@3 | B R@5 | B MRR@5 |
|---|---|---|---|---|---|---|---|---|
| main29 | 0.9310 | 1.0000 | 1.0000 | 0.9540 | 0.9310 | 1.0000 | 1.0000 | 0.9598 |
| mini9 | 0.4444 | 0.7778 | 0.8889 | 0.6148 | 0.2222 | 0.6667 | 0.8889 | 0.4759 |
| validation14 | 0.8571 | 0.9286 | 0.9286 | 0.8810 | 0.8571 | 0.9286 | 0.9286 | 0.8810 |
| pooled | 0.8269 | 0.9423 | 0.9615 | 0.8756 | 0.7885 | 0.9231 | 0.9615 | 0.8548 |

Losses (A hits, B does not): R@1 3, R@3 1, R@5 0; gains: R@1 1. Incident pairs in the final top 5: 3/5 in both arms. Rule: adopt only with no loss - **not met, keep `rrf_blend`**. `rerank.DEFAULT_RERANK_MODE` is unchanged, so no deviation from the blind-run protocol arises.

- Expected documents that are not vector hits: 14. In the candidate pool: 7. In the final top 5: **0 in arm A, 0 in arm B** (best pool ranks: A 7-13, B 7-15). The other 7 are not in the pool at all. The audit's finding stands: removing the blend does not make appended gold documents reachable.
- Appended documents in the CrossEncoder top 5 that the blend pushed out of the top 5 (the audit counted 19; this run finds 18): in arm B all 18 reach the top 5 (by construction), and none of them is a gold document. So on these questions the blend suppresses appended documents that are not the expected ones; arm B's R@1 losses come from reordering among vector hits.

## Step 6 - hardened graph profile

Run after steps 4 and 5 in their accepted states. Pooled R@1 0.8269 / R@3 0.9423 / R@5 0.9615 / MRR@5 0.8756 in both arms, every per-set value equal, 0 losses and 0 gains, incident 3/5 in both. The rule requires at least one gain: **not met, keep the legacy profile.** `pipeline.GRAPH_KWARGS` ({} by default) is the switch; setting it to `{"hub_fraction": 0.05, "specificity": True, "max_documents": 3}` selects the hardened profile.

## Settings that no longer change ranking (documented as switches)

- Gate tiers 0.5 / 0.15 (`query_gate.graph_weight`): `fusion` treats `graph_weight` as on/off (> 0 includes the graph list). 0.5 and 0.15 behave identically; only 0.0 differs.
- `LINK_WEIGHT = 0.15`: on/off for the link list only.
- `VECTOR_WEIGHT = 1.0` in `fusion.py`: kept for compatibility; the vector list defines the order.

## What is NOT shown

Everything here is measured on the 52 development questions the system was developed on. "No loss" and "no gain" verdicts cannot resolve differences below one question and are not generalisation evidence; the incident check is five pairs. Step 3 shows only that retrieval did not move, not that the concept layer helps. Person A's 42 questions remain the unbiased test and were not used.
