# NovaTel E14 Integrated RAG -- Pipeline Review Digest

_Generated 2026-10-14 from real result files only. Missing values are written as "not available"._

## 1. Run identity
- File: `data\experiments\integrated_rag\20261013T183747Z_E14-subset.json`
- Timestamp (from filename): `20261013T183747Z`
- Run id: `E14-subset`, n_queries=10
- Newest run on disk: **yes** (1 run file(s) found in data/experiments/integrated_rag/)

## 2. Config
- LLM model (code default, `integration/rag/llm_client.py:11`): `qwen2.5:7b-instruct` (actual run value not recorded in result JSON; env-var overridable)
- Quantization: not available
- Detected GPU / VRAM / system RAM: not available (not persisted to any result file)
- Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (source: `data\experiments\public_pdfs\public_pdf_retrieval_evaluation.json`)
- Fusion: RRF, k=60 (source: `integration/rag/fuse.py:9`)
- Context: top-N=6 (source: `integration/rag/context_builder.py:7`)
- Judge model: not available (not recorded in result JSON; eval-harness code not in this task's read scope)
- Eval queries: 10 total -- {'unstructured': 4, 'structured': 5, 'hybrid': 1} (source: `20261013T183747Z_E14-subset.json`)

## 3. Pipeline-as-built (from code)
- `pipeline.py::RagPipeline.run_query()`: calls `StructuredSearchAdapter.search()` (SQL, `structured/retriever.py`) and `UnstructuredSearcher.search()` (FAISS top-10 + CrossEncoder rerank over the combined 1545-chunk index) independently.
- `fuse.py::reciprocal_rank_fusion()`: rank-only RRF (k=60) merges the two Common-Schema lists; SQL and FAISS scores are never summed or compared numerically.
- `context_builder.py::build_context()`: drops candidates with <5 chars content, dedups by (source,dataset,record_id), keeps top-6, labels each block with provenance.
- `generate.py::generate_answer()`: fixed system prompt forces citation-per-claim, structured-vs-document separation, and abstention on empty context; temperature=0 via `OllamaClient`.
- No KG, ontology, or ColPali call anywhere in this chain (confirmed by reading the 4 files above).

## 4. Answer metrics (DeepEval, LLM-judged)
Source: `20261013T183747Z_E14-subset.json` -> `deepeval_metrics`

| Metric | Overall (n=10) | Structured (n=5) | Unstructured (n=4) | Hybrid (n=1) |
|---|---|---|---|---|
| Answer Rel. | 0.984 | 1.000 | 0.952 (1 excl.) | 1.000 |
| Ctx Rel. | 0.204 | 0.082 | 0.320 (1 excl.) | 0.467 |
| Faithfulness | 0.800 | 0.933 | 0.833 | 0.000 |
| Ctx Precision | 0.967 | 0.951 | 0.979 | 1.000 |

## 5. Deterministic retrieval vs. DeepEval contextual precision
Source: `20261013T183747Z_E14-subset.json` -> `deterministic_metrics` (same 10-query run)

| R@1 | R@3 | R@5 | R@10 | MRR@10 | Structured table-hit | DeepEval Ctx. Precision (overall) |
|---|---|---|---|---|---|---|
| 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.967 |

For broader (NOT directly comparable -- different, pre-existing, larger query sets) context: synthetic 29-Q Top-1/3/5 = 0.759/0.897/1.000 (MRR@10: not available, field absent) -- `data\vectorstore\retrieval_evaluation.json`; public 30-Q R@1/3/5/10/MRR@10 = 0.467/0.767/0.900/1.000/0.645 -- `data\experiments\public_pdfs\public_pdf_retrieval_evaluation.json`.

## 6. Deterministic factcheck vs. Faithfulness
Source: `20261013T183747Z_E14-subset.json` -> `factcheck` + `deepeval_metrics.aggregate.FaithfulnessMetric`

- Structured-fact claims checked: **7**, unsupported/mismatched: **0**
- DeepEval Faithfulness (overall, LLM-judged): **0.800**
- Coverage gap: checked claims are concentrated in structured-type queries ({'unstructured': 0, 'structured': 7, 'hybrid': 0}); unstructured/hybrid answers have little-to-no deterministic corroboration for their Faithfulness scores.

## 7. Failure split
retrieval-failure=0 (R@1 and structured_table_hit_rate both =1.0 over n=10 -> 0 misses), generation-failure=4 (Faithfulness<1.0 despite correct retrieval), both=0, ambiguous(judge error)=0

## 8. Sample query traces
- **S03** (structured) Q: "Show invoices for customer 1009"
  A: Invoices for customer 1009 are as follows:  - Invoice ID 5019, for the billing cycle from 2026-03-01 to 2026-03-31, with a total amount of ₹3596.91, which is Overdue [E1]. - Invoice ID 5020, for the billing cycle from...
  Citations: E1, E3, E5 | Faithfulness=1.0 | Verdict: grounded -- 3 invoices, all cited to structured evidence, factcheck 3/3 supported.
- **Q04** (hybrid) Q: "Why is my latest postpaid bill higher than the monthly rental I expected to pay?"
  A: Based on the evidence provided, your latest postpaid bill is higher than the monthly rental you expected to pay due to additional charges beyond the base plan rental. These additional charges can include:  - Pro-rated...
  Citations: E2, E4 | Faithfulness=0.0 | Verdict: weakest case -- Faithfulness=0.00 per judge (claims not supported by context); factcheck found 0 claims to check (no structured citation to verify against).

## 9. Red flags
- R@1, R@3, R@5, R@10, MRR@10, structured_table_hit_rate all = 1.0 on a very small n (unstructured n=5, structured n=5) -- likely small-sample artifact, not proof of robustness.
- 0 of 4 unstructured queries in this subset are public-corpus (`RW_*`) -- the public TRAI-PDF retrieval path was not exercised at all in this run.
- Deterministic factcheck only ever checked structured-type queries (0 checked claims on unstructured/hybrid answers) -- it provides NO corroboration for the Faithfulness=0.00 case below (Q04, hybrid), since that answer cited no structured evidence.
- 2 DeepEval judge call(s) returned a JSON-parse error and were excluded from aggregates (see per_query in result file).
- Lowest Faithfulness score: Q04 = 0.00 (see sample trace below).

## 10. Eval caveats
- CAVEAT: AnswerRelevancy, ContextualRelevancy, Faithfulness and ContextualPrecision above are judged by a local 7B/3B Ollama model (qwen2.5), not a ground-truth human or a large frontier model. These scores must be human spot-checked before being treated as reliable -- they are a signal, not ground truth. Compare them against the deterministic R@k/MRR@10 numbers (no LLM involved) printed alongside.
- Sample size: 10 queries ({'unstructured': 4, 'structured': 5, 'hybrid': 1}) -- a full 74-query run (29 synthetic + 30 public + 15 structured) was in progress but not complete as of this digest.
- Scope: E14 = structured SQL + unstructured FAISS/metadata retrieval + local LLM only. No knowledge graph, ontology, or ColPali were used in this run.
