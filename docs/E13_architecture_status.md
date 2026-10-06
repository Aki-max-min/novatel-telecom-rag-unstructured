# E13 hybrid layer - architecture status

Status of each stage of the pipeline on branch `person-b/hybrid-e13`, with the evidence and the known limitation.
"Built" = code exists. "Tested" = unit tests exist and pass (full suite: see the end). "Known limitation" cites the post-hoc
log (`docs/E13_phase8_posthoc_log.md`) wherever the limit comes from a post-hoc change or a measured miss.

```
question, customer_id (session), as_of
  -> [1] clause analysis + query gate  (hybrid/clauses.py, query_gate.py, textmatch.py)
  -> [2] router + identity / privacy guards  (hybrid/router.py)
        |-- structured channel: [3] customer-scoped read-only adapter  (hybrid/structured_adapter.py)
        '-- document channel : [4] vector + graph candidates -> [5] document-level RRF fusion + dedup
                                 -> [6] controlled CrossEncoder rerank          (retrievers.py, fusion.py, dedup.py, rerank.py)
  -> [7] context assembly: F1..Fn facts and D1..Dk documents, two separate channels  (hybrid/context.py)
  -> [8] answer: extractive (default) or LLM (off)  (hybrid/answer.py)
  -> [9] deterministic groundedness verifier  (hybrid/groundedness.py)
```

| # | Stage | Built | Tested | Known limitation |
|---|---|---|---|---|
| 1 | Clause analysis + gate (personal / policy / hypothetical; concept hint; graph weight 0.5 / 0.15 / 0.0) | yes | yes: shared-matcher property test (630 keyword checks), Phase 8 / 8d / 8e unit tests, 7 probes, new-sentence leak scans | Rule-based and a post-hoc fit (fixes 1-10 in the log). "when I tried ..." narrative reads as hypothetical and conditional inheritance swallows the next clause; personal context without a possessive or without a listed fact term is not detected; keyword concept hints are crude (see "Known limitations of the accepted router"). Query understanding is joint-design territory with Person A (roadmap Section 7). |
| 2 | Router: structured / unstructured / both; needs_identity; refuse_other_customer; third-party and other-number guards; unrecognised-request flag | yes | yes: router, Phase 8a fixes, probes, frozen benchmark runs (leakage 0 in every run) | The third-party rule refuses some policy questions ("merge my plan with my wife's"). Headline is the untuned first run (route 21/24, fact recall 23/30); amended-3 (24/24) is a post-hoc fit. No blind-set result yet. |
| 3 | Customer-scoped read-only structured adapter (5 intents, allow-listed fields, msisdn masked, derived flags labelled) | yes | yes: verified anchors, 25 customers x all intents = 0 leakage, read-only write attempts raise, parameterised-SQL scan | Stored values reported verbatim; the data has inconsistencies (Unpaid invoice with full SUCCESS payment; Active subscriptions with past expiry) that are surfaced as derived flags, never "fixed". Invoice answers do not include the charge breakdown (plan/usage/VAS/tax). |
| 4 | Vector + graph candidates (Person A's FAISS index, KG expansion) | yes (reused, not reimplemented) | yes: Phase 5 metrics reproduced exactly after the refactor | Document-level (best chunk per document). |
| 5 | Document-level weighted RRF fusion (k = 60) + dedup | yes | yes: hand-checkable arithmetic tests, document-key tests, 0-weight excludes graph-only candidates | Graph weight comes from the gate, so gate errors move rankings (nine main/mini weights moved in Phase 8e). |
| 6 | Controlled rerank: pool capped at 20; default V1 rrf_blend (w = 1.0) | yes | yes: pool-cap evidence, mode arithmetic tests, real CrossEncoder run | V1 was selected by a pre-declared rule whose macro-average over-weights the 9-question set (addendum in `docs/E13_phase8_rerank_selection_rule.md`); on pooled data V0 and V1 are indistinguishable. The shipping default is to be decided on a blind set (adopt V1 only if pooled MRR@5 beats V0 by >= 0.02). |
| 7 | Context assembly with notices | yes | yes | Snippets are cleaned only for line-start metadata headers; some documents keep an inline "Document ID: ... Category: ..." header in the snippet. Chunk boundaries can start a snippet mid-sentence. |
| 8 | Extractive answerer (default); LLM answerer behind one interface (off) | yes | yes: anchors for customers 1042 / 1056 / 1829, silence rule, notices, fake-LLM fallback tests (no network) | Quotes are whole sentences picked by token overlap, so they can be long or only loosely relevant. Model choice, prompt design and cost are a joint decision with Person A; no model is configured by default. |
| 9 | Deterministic groundedness verifier (5 rules) | yes | yes: 30 of 30 mutants of 6 grounded answers flagged by the expected rule | Checks citations, numbers/dates, masked identifiers and safety wording, not meaning: an uncited absence claim ("I found no tickets") or a wrongly-chosen quote passes. |

## Evidence

- Phase 5 (original design vs real benchmarks): the rerank, not the gate, produced the main-benchmark gain; no gain over Person A's existing reranker (`docs/E13_Hybrid_Fusion_Roadmap.md` Section 8).
- Frozen route benchmark (24 questions; `hybrid/benchmark/`): first run route 21/24, outcome 24/24, fact recall 23/30, leakage 0 (the headline); amended-1 / -2 / -3 are labelled post-hoc (`docs/E13_phase8_posthoc_log.md`).
- Answer layer (`hybrid/benchmark/answer_eval_phase9c.json`, extractive, deterministic): verifier 24/24, citation validity 24/24, fact inclusion 29/30, needs_identity and refusal safety items pass. Re-run after two post-hoc fixes: `answer_eval_phase9c_postfix.json` (same metrics; fixes logged below).

## Post-hoc fixes in the answer layer (found by reading sample answers, not by a metric)

1. With no customer, the extractive answer said "I found no recharges on your account" - false, since nothing was looked up. Absence sentences are now only produced for an identified customer.
2. Quotes could be unreadable markdown-table fragments. Sentences containing table markup are skipped and quotes over 450 characters are avoided when a shorter sentence exists.
The one fact-inclusion miss (RB_B06: the answer does not state `plan_charge`) was left as measured.

## Open items for the joint sync with Person A

- Whether and which LLM sits behind the answerer, with what prompt and cost budget (module docstring in `hybrid/answer.py`).
- Redesign of the gate's signal for graph-dependence (roadmap Section 8 open question 1) and graph-vs-rerank treatment (open question 2).
- The blind set: unwritten. It is the real generalisation test for the router and for the V1-vs-V0 rerank default.
- The `docs/` and `hybrid/` additions live only on this branch; nothing outside `hybrid/` and `docs/` was modified.
