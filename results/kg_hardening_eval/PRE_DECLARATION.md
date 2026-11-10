# Pre-declaration: KG-hardening evaluation in Person A's pipeline

Written 2026-11-10 (UTC), before any evaluation run (before the smoke test as well).
Branch `exp/kg-hardening-eval`, HEAD at the time of writing = `abf055a` (merge of `origin/person-b/kg-hardening`).
Nothing in this file is changed after results are seen.

## Code under test

| item | value |
|---|---|
| merged commit (Person B) | `700a5dd58e7d9be0c36518bb4e574f090d5a1a76` (tip of `origin/person-b/kg-hardening`) |
| handoff commit named in Person B's message | `83a8aa77523fe28dae4677443709bfb76c261d2c` (an ancestor of the tip) |
| the 8 commits in between | touch only Person B's `hybrid/` link-decoupling code (fusion.py, pipeline.py, retrievers.py, two scripts, tests), `knowledge_graph/tests/test_graph_expand.py` and docs. `knowledge_graph/graph_augmented_retrieval.py`, `build_related_aliases.py` and `graph_builder.py` are byte-identical between the two commits (verified with `git diff --stat 83a8aa7 700a5dd`). Person B's `links_enabled` / link-fusion path in `hybrid/` is NOT evaluated here. |
| merge conflicts | `.gitignore` only (both sides appended lines; both kept) |
| v3 reference | commit `2fdffad`, results in `results/perf_report/` (read-only for this evaluation) |
| interpreter | `.venv_colpali/Scripts/python.exe` (Python 3.12.10, torch 2.14.0+cu130, transformers 5.16.1, sentence-transformers 5.6.0, faiss-cpu 1.15.0, numpy 2.5.2, ollama 0.6.3): the package set recorded in the v3 manifest |
| graph | `knowledge_graph/output/graph.json` rebuilt by `python -m knowledge_graph.build_related_aliases` + `python -m knowledge_graph.graph_builder` (logs in `setup_logs/`). 47 of 84 RELATED_TO links resolve; non-RELATED_TO edges and non-stub nodes are identical to the graph v3 used (`setup_logs/graph_rebuild_check.json`) |

## The four configurations (exact settings)

Everything not listed is identical across arms: `qwen2.5:7b-instruct` Q4_K_M via Ollama, temperature 0, seed 42, E14a prompts, SciFact
serving-time filter ON, answer cache OFF, prompt budget 5 database + 3 document blocks (`RagConfig.b2()`), FAISS top-10 + CrossEncoder, RRF k=60,
`GRAPH_SEEDS` 5, `GRAPH_CANDIDATES` 20, `semantic_max_chunks_per_doc` 2, the query gate's graph weight (0.5 / 0.15 / 0.0), the router as calibrated
(auto chain laya_finetuned -> embedding -> rule, confidence threshold 0.5, incident routing untouched), 3 runs per arm, the 42 questions of
`eval/perf_report/questions.jsonl` with their gold.

| arm | layer | `graph_expand` keyword arguments | `use_related_links` | router | citation check |
|---|---|---|---|---|---|
| `B2` | none | n/a | n/a | off | on (flagging only) |
| `C_V0` | `SemanticLayer` (ontology term normalisation + document-graph expansion) | none (legacy profile "V0") | `False` | on | on |
| `C_V1` | same | `hub_fraction=0.05, specificity=True, max_documents=3` | `False` | on | on |
| `C_V1_links` | same | `hub_fraction=0.05, specificity=True, max_documents=3` | `True` | on | on |

Where the knobs live (verified in code, nothing invented):

* `hub_fraction`, `specificity`, `max_documents` are keyword-only arguments of `knowledge_graph.graph_augmented_retrieval.graph_expand`
  (Person B's code). Our `integration/rag/semantic_layer.py` calls `graph_expand(seeds, graph_index, bridges=..., limit=...)` and does not forward
  them, so the harness subclass `HardenedGraphLayer` (`eval/kg_hardening_eval/harness_kg.py`) wraps the same call with `functools.partial` and
  the three arguments. With no arguments it is the legacy call. No repository module is edited.
* `use_related_links` is the existing constructor flag of `SemanticLayer`. Its default is `True`; the v3 arm C ran with that default when 0 of 84
  links resolved (the hop added nothing). `C_V0` and `C_V1` set it `False` explicitly so that only `C_V1_links` carries the link effect.
* Arm labels and layer settings are checked against each other before every generation (`check_layer`) and stored in every raw record (`arm_config`).

## Comparison plan

Primary: correctness with partial credit (mean of 0/1/2 as % of max, mean over the 3 runs) on all 42 questions.

Also reported for every arm (n/a or "not scored" rather than blanks): relevance; groundedness; hallucination vs reference evidence and vs retrieved
context (every arm judged at the full level, including B2); citation coverage, citation correctness, unsupported-claim rate (every arm); R@1, R@3,
R@5, R@10, MRR@10 on the 25 document questions and database-row coverage; latency median / p95 and median prompt tokens; per-category
correctness (db, syn, trai, cross, multi); run-to-run variability; error-cause counts with the v3 rule (`eval/perf_report/run_report.classify`);
graph diagnostics per C arm (chunks added, via bridge concept vs RELATED_TO, documents added per question, added chunks relevant to the gold
evidence by the v3 rule "added document is a gold document", questions where graph chunks displaced the gold document from the top 10).

Paired comparisons, each under three scoring rules (strict: fully correct in a majority of runs; partial credit: per-question mean score;
lenient: score >= 1 in a majority of runs), with wins / losses / ties, exact two-sided McNemar p and a paired bootstrap 95% CI (10,000 question
resamples, seed 20261031, as v3): `C_V1` vs `C_V0`; `C_V1_links` vs `C_V1`; each C arm vs `B2`; `B2` (this branch) vs `B2` (v3); and, as a drift check,
`C_V0` (this branch) vs `C` (v3).

Interpretation rules fixed now:

* `B2`-new vs `B2`-v3 is reported as a separate line (parser effect plus run-to-run noise). Graph effects are judged only within this branch
  (`C_V0` / `C_V1` / `C_V1_links` vs `B2`-new). The graph is neither credited nor blamed for parser effects.
* If `C_V0` does not reproduce v3 C within normal noise, candidate causes (parser fixes, alias build, graph rebuild) are stated as inference.
* 42 questions and 3 runs give low power; a difference of a few questions is reported as such, not as a finding.

## Known before the run (reported, not fixed)

* Person B's merged branch changes the structured side. On this branch the default-config golden-prompt test
  (`integration/tests/test_rag_defaults_identical.py`) fails on Q04 (the old parser returned invoice rows 5001/5002/5004 for "Why is my latest
  postpaid bill higher...", the merged parser returns no structured result), and 5 tests in `integration/tests/test_structured_guard.py` fail
  (`setup_logs/17_pytest_merged_branch_full.log`, `18_structured_guard_failures.log`). All other tests pass (390 passed). These affect every arm
  equally and are the reason `B2` is re-run on this branch.
* The first attempt at `python -m knowledge_graph.graph_builder` ran with the wrong interpreter (system Python without the project packages) and
  failed on `networkx`; the command was re-run unchanged with `.venv_colpali` and passed. Nothing was installed (`setup_logs/README.md`).

## Frozen

* No parameter (hub_fraction, specificity, max_documents, use_related_links, gate weights, seeds, candidates, chunk cap, budget, router threshold,
  routing rules, prompts, decoding) is changed after seeing any result. Each configuration runs exactly once (3 runs = the fixed protocol).
* No question is added, removed or re-labelled; `eval/perf_report/questions.jsonl`, the gold, the judge prompts and the scoring code stay as in v3.
* `results/perf_report/` is never written to. The v3 judge cache is read, never appended; new judge verdicts go to this experiment's own cache.
* A bug found during the run is reported in `STATUS.md`; the run is not silently re-tuned or re-run with different settings.
* Smoke test (3 questions x 4 arms, run 1, plus a no-LLM retrieval comparison of the three C layers on all 42 questions) decides only whether the
  settings are applied: proceed if every record's arm label matches its configuration AND `C_V1` retrieval differs from `C_V0` on at least one
  question; otherwise stop and report. Smoke records are not part of the measurement.
