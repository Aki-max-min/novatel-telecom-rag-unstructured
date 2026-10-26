# integration/rag — E14 Integrated RAG (structured + unstructured only)

First end-to-end fused pipeline: query -> both EXISTING retrievers ->
controlled fusion -> compact context -> local LLM -> grounded answer ->
answer-quality metrics.

## Scope lock

This connects only:
- `structured/retriever.py::StructuredRetriever` (SQL, 28 tables)
- the existing combined FAISS index from E9
  (`data/experiments/combined_retrieval/vectorstore/`, 383 synthetic +
  1162 public TRAI-PDF chunks = 1545 total)

It does **not** wire in the structured knowledge graph, shared ontology, or
document graph that exist upstream (on `origin/main` /
`origin/person-b/hybrid-e13`, not merged into this local checkout at the
time this package was built) or ColPali. Those are later experiments by
design (see the task's scope lock).

## Pieces

- `llm_client.py` — thin wrapper on `ollama.chat()`, temperature=0, fixed
  seed, model name from `NOVATEL_LLM_MODEL` env var (default
  `qwen2.5:7b-instruct`).
- `fuse.py` — Reciprocal Rank Fusion (k=60), rank-based only. Structured
  and unstructured scores are never added or compared numerically; RRF
  only ever looks at each candidate's rank position within its own
  source's list.
- `context_builder.py` — dedups, drops empty/near-empty candidates, keeps
  the top-N (default 6), and labels every evidence block with its
  provenance (source, dataset, record_id/chunk_id, page if any).
- `generate.py` — the prompt contract: answer only from evidence, cite
  `[Ek]` ids for every factual claim, separate structured facts from
  document evidence, abstain on insufficient evidence.
- `pipeline.py` — `RagPipeline` holds both retrievers' loaded models once
  (construct it once per process; re-running `UnstructuredSearcher()` per
  query would reload the embedding + CrossEncoder models every time).

### `UnstructuredSearcher` — a disclosed simplification

`ingestion/hybrid_rerank_retrieval.py`'s hybrid score blends a CrossEncoder
score with a *title/category boost that uses the benchmark's ground-truth
expected category*. A live query has no such ground truth. `pipeline.py`'s
searcher is therefore **FAISS top-k + CrossEncoder rerank only** — the
title/category boost is not silently reproduced with a fake category. This
is why its `hybrid_score` differs in meaning from the offline eval's.

## integration/eval

- `factcheck.py` — deterministic (no LLM) structured-fact checker. Finds
  `[Ek]` citations into structured evidence in the generated answer, and
  exact-matches any number/ID/status/count token in the citing sentence
  against that evidence record's real metadata values. This is a
  sentence+citation heuristic, not full claim-level NLU — disclosed as
  such in its own docstring.
- `answer_eval.py` — four DeepEval metrics (AnswerRelevancy,
  ContextualRelevancy, Faithfulness, ContextualPrecision), judged by the
  SAME local Ollama model used for generation (`OllamaDeepEvalModel`), plus
  deterministic R@1/R@3/R@5/MRR@10 computed with no LLM at all, so the two
  can be compared directly. See `run_eval(limit=...)`.

### The one metric that needed a ground-truth answer

`ContextualPrecisionMetric` is the only DeepEval metric here that
structurally requires `expected_output`. Rather than invent a model
answer, `_expected_output_proxy()` builds a short, mechanically-derived
proxy string straight from ground truth that already exists in the repo
(`expected_document_ids` for unstructured queries, `expected_table`/filter
for structured queries) — e.g. *"A correct answer must be grounded in
evidence from document(s): FAQ_C01_001."* Every saved eval record is
transparent that this proxy, not a real answer, was used.

### Faithfulness-judge caveat (printed with every report)

LLM-judged metrics use a local 7B/3B model as judge. They are a signal,
not ground truth, and should be human spot-checked — compare them against
the deterministic R@k/MRR@10 numbers printed alongside, which involve no
LLM at all.

## Running

```
python -m integration.eval.answer_eval 10    # subset smoke test
python -m integration.eval.answer_eval 74    # full set (29 synthetic + 30 public + 15 structured)
```

Results are saved as timestamped JSON under
`data/experiments/integrated_rag/`, never overwritten.
