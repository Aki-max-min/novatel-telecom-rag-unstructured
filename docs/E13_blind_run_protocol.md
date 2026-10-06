# E13 blind-run protocol (declared BEFORE any blind file exists)

Purpose: obtain one generalisation measurement of the E13 pipeline on questions that nothing in this codebase has been fitted to.
Everything measured so far on the frozen route benchmark after the untuned first run is labelled post-hoc (fitted); see
`docs/E13_phase8_posthoc_log.md`.

## Rules

1. **Freeze.** At freeze the code is tagged `e13-frozen`. The tag is created when the project owner says so; it does not exist yet and
   nothing here creates it. After the tag, **no code changes until the blind run is finished.** (Documentation edits that do not
   change behaviour are allowed; the findings section below is one.)
2. **The blind file** is authored independently of this codebase and delivered once. It is run **once**, and **every number is
   reported** - including the ones that look bad. No question is dropped, re-worded or re-run.
3. **One router.** Only the accepted clause router (`hybrid/clauses.py`, accepted at `87d4529`) is evaluated. The earlier idea of
   comparing two router versions is dropped to keep the code simple.
4. **The rerank default** is decided on the blind set's unstructured and both items only: **V1 (`rrf_blend`, w = 1.0) is adopted only if
   its pooled MRR@5 beats V0's (`override`) by at least 0.02; otherwise the default is V0** (per the addendum in
   `docs/E13_phase8_rerank_selection_rule.md`). Both variants are computed on the same shared CrossEncoder scores in the same run.
   Changing `DEFAULT_RERANK_MODE` after that decision is a configuration change recorded in this document, not a code change that
   invalidates the run.
5. **Problems found by the blind run** go in a "Findings after the blind run" section of this document and are **not fixed in the same
   run.** Any fix is a separate, labelled, post-hoc change made afterwards and reported next to - never instead of - the blind numbers.
6. **Headline.** The blind-set numbers are the headline for generalisation. All earlier post-hoc numbers (amended-1, -2, -3, the
   post-fix and second answer-evaluation runs) are labelled as fitted; the untuned first run of the frozen route benchmark remains
   the headline for that benchmark only.

## What is reported (all of it, from the single run)

- Route accuracy (3-class, with confusion matrix) and outcome accuracy.
- Structured fact recall and **leakage** (must be 0; any non-zero value is reported first).
- Document hit@3 / hit@5 for unstructured and both items, with the full pipeline and the real CrossEncoder.
- Safety items: needs_identity (zero facts) and refuse_other_customer (zero facts and zero documents).
- Answer layer, extractive and deterministic: verifier pass rate, citation validity, fact inclusion, and the absence-claim check.
- The V0-vs-V1 pooled MRR@5 comparison and the resulting rerank default.
- Every miss, with the question, the router decision and reason string, and what was expected.

## Findings after the blind run

(empty - to be filled in after the run, without code changes)
