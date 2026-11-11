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
