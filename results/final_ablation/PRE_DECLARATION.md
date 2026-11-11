# Pre-declaration: final component ablation on one code state

Written 2026-11-11 (UTC), before any generation (before the smoke test as well).
Branch `exp/kg-hardening-eval`, HEAD at the time of writing = `6956902` (last commit of the KG-hardening evaluation).
`origin/person-b/kg-hardening` is still at `700a5dd` (checked with `git fetch`); nothing new was merged.
Nothing in this file is changed after results are seen.

## Purpose

Close the gaps of the v4 performance report so that every arm comes from ONE code state (this branch, which includes Person B's merged
parser / KG hardening): base LLM and RAG baseline re-run on this branch; the component ablation (router only, ontology only, graph only)
re-run on this branch; graph-only arms with the legacy and the hardened graph so that the graph effect can be separated from the router effect.

## Arms

Generated here (3 runs x 42 questions each, order arm -> run -> question):

| arm | meaning | exact settings (names as in code) |
|---|---|---|
| A | base LLM, no retrieval | `arm_settings: {"retrieval": False}`; E14a `BASE_SYSTEM_PROMPT` |
| B | RAG baseline | `RagConfig()` (shared 6-block prompt limit, `per_source_budget=None`), no router, no layer |
| R | B2 + router only | `RagConfig.b2()` (5 db + 3 doc blocks); `router=True` (auto chain laya_finetuned -> embedding -> rule, `router_conf_threshold` 0.5); layer None |
| O | B2 + ontology hint only | `RagConfig.b2()`; layer = v3 `OntologyOnlyLayer` (concept hint -> canonical terms appended to the FAISS query; `neighbours()` returns `[]`, so no graph candidates); `use_related_links=False`; router off |
| G0 | B2 + legacy graph expansion only | `RagConfig.b2()`; layer = v3 `DocGraphOnlyLayer` (FAISS query NOT expanded with ontology terms; the query gate's graph weight 0.5 / 0.15 / 0.0 is kept); `graph_expand` with no keyword arguments; `use_related_links=False`; router off |
| G1 | B2 + hardened graph expansion only | as G0 with `graph_expand(hub_fraction=0.05, specificity=True, max_documents=3)` (wrapped by `functools.partial`, no repository module edited) |
| G1L | G1 + RELATED_TO hop | as G1 with `use_related_links=True` (our `integration/rag/semantic_layer.py` hop; 47 of 84 links resolve) |

Reused, not re-run (loaded from `results/kg_hardening_eval/raw_answers.jsonl` / `scored_answers.jsonl`, 126 records each, arm labels and stored
`arm_config` verified against `harness_kg.arm_settings`; produced at commit `6f4f0fa`, whose retrieval/generation code, `graph.json` and index are
identical to HEAD, verified by `git diff --name-only` over `integration/ structured/ knowledge_graph/ hybrid/ query_router/ ontology/ eval/perf_report/
data/eval/` and by the graph's sha256 before the manifest is written):

| arm | meaning |
|---|---|
| B2 | B + per-source budget 5 db + 3 doc (`RagConfig.b2()`), no router, no layer |
| C_V0 | B2 + router + full semantic layer (ontology terms + legacy graph expansion), `use_related_links=False` |
| C_V1 | C_V0 with `hub_fraction=0.05, specificity=True, max_documents=3` |
| C_V1_links | C_V1 with `use_related_links=True` |

Everything not listed is identical across arms: `qwen2.5:7b-instruct` Q4_K_M via Ollama, temperature 0, seed 42, E14a prompts, SciFact serving-time
filter ON, answer cache OFF, FAISS top-10 + CrossEncoder, RRF k=60, `GRAPH_SEEDS` 5, `GRAPH_CANDIDATES` 20, `semantic_max_chunks_per_doc` 2,
the query gate's graph weight, the router as calibrated, the 42 questions of `eval/perf_report/questions.jsonl` with their gold.

"Router OFF" = exactly B2's behaviour in `h.Rig.generate`: no routing, both sources searched (`use_structured = use_docs = True`).
"Ontology setting in G0 / G1 / G1L" = the v3 `docgraph_only` convention: no ontology terms in the FAISS query, gate weight kept.
`use_related_links`: the v3 ontology/docgraph arms ran the default `True` when 0 of 84 links resolved (no-op); O, G0 and G1 set it `False`
explicitly so that only G1L carries the link effect (the convention of the KG-hardening run).

Structured KG arm: stays "not run (not wired into retrieval)"; `QAConfig.use_structured_kg` is read by no retrieval code. A wiring plan is
written to `docs/STRUCTURED_KG_WIRING_PLAN.md` (plan only, nothing implemented).

## Metrics and comparisons

For every arm: correctness (partial credit = mean score / 2; strict = fully correct in a majority of runs; lenient = score >= 1 in a majority
of runs), relevance, groundedness, hallucination vs reference and vs retrieved context, citation coverage / correctness / unsupported-claim rate,
R@1/3/5/10 and MRR@10 on the 25 document questions, database-row coverage, latency median / p95, median prompt tokens, per-category correctness
(db 15, syn 8, trai 6, cross 6, multi 7), the original-22 (E14a core) correctness, run-to-run variability. "n/a" where a metric cannot exist
(A: groundedness, hallucination vs context, citations, retrieval, row coverage).

Paired comparisons (42 pairs; wins / losses / ties, exact two-sided McNemar on the discordant pairs, paired bootstrap 95% CI with 10,000
question resamples, seed 20261031 as v3) under the three rules for: R vs B2, O vs B2, G0 vs B2, G1 vs B2, G1L vs B2, G1 vs G0, G1L vs G1,
C_V1 vs G1, C_V0 vs G0, C_V1 vs R, B2 vs B, B vs A.

Component-ablation table: each row adds ONE component to B2. 2x2 views: {B2, R, G1, C_V1} and {B2, R, G0, C_V0}.

Error causes: the v3 deterministic rule `eval/perf_report/run_report.classify` (unchanged since v3 commit `dc481b6`; `git diff dc481b6 HEAD --
eval/perf_report/` is empty), one cause per answer with correctness < 2, B2 of the same run as reference for the router/layer arms. The
reconciliation of the v3 C vs C_V0 label split is analysis only; the rule is NOT changed to make tables agree.

Graph diagnostics for G0, G1, G1L in the format of `results/kg_hardening_eval/graph_diagnostics.md` (reference arm B2, run 1).

## Frozen

* No parameter (hub_fraction, specificity, max_documents, use_related_links, gate weights, seeds, candidates, chunk cap, budgets, router
  threshold, routing rules, prompts, decoding) is changed after seeing any result. Each configuration runs exactly once (3 runs = the protocol).
* The 42 questions, the gold, the judge prompts, the scoring code, the seeds and the router (Laya checkpoint, threshold, incident routing)
  are not touched. `results/perf_report/` and `results/kg_hardening_eval/` are never written to; outputs go to `results/final_ablation/`.
* The judge caches of v3 and the KG-hardening run are read, never appended; new judge verdicts go to this experiment's own cache.
* A bug found during the run is reported in `STATUS.md`; the run is not silently re-tuned or re-run with different settings.
* Smoke test (3 questions x 7 generated arms, run 1, plus a no-LLM retrieval comparison of the four layers against the plain B2 search on all
  42 questions) decides only whether the settings are applied: proceed if every record's arm label matches its configuration, A has no
  retrieval, only R has a route, O adds no graph chunks and rewrites at least one query, G0 adds chunks somewhere, AND G1 retrieval differs
  from G0 on at least one of the 42 questions; otherwise stop and report. Smoke records are not part of the measurement.
* Generation for all arms first, then judging. The generation stage refuses to start on battery power (the machine reads "discharging" at the
  time of writing) unless explicitly overridden; sleep-after is 0 on AC and DC (`powercfg`).

## Known before the run (reported, not fixed)

* Six tests fail on this branch (Q04 golden prompt; 5 structured-guard tests), from Person B's structured-side changes. Analysed in
  `failing_tests.md`, not fixed.
* The error-cause figures quoted in the task for the v3 C arm (graph 12, context 0, ranking 3) do not match `results/perf_report/error_table.csv`
  (graph 3, context 6, ranking 6, retrieval 12, router 12, model 9, competing 3). The reconciliation works from the files.
