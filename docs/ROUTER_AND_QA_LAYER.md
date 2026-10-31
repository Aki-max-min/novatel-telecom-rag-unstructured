# Router + grounded-QA layer (Person A)

Flow implemented by `integration.qa.system.answer_query(query, config)`:

```
Query
  -> Router (query_router/)        multi-label: in_scope / needs_structured / needs_unstructured
       out_of_scope ------------------------------> ABSTAIN (layer 1)
       confidence < calibrated threshold ----------> treated as HYBRID
  -> structured | unstructured | hybrid (decomposed into two sub-queries, retrieved independently)
  -> retrieval-confidence gate -> ABSTAIN (layer 2) | one-shot retry against the other source (logged)
  -> rank-based fusion (RRF, k=60) -> stable evidence ids E1..En
  -> grounded generation (local Ollama; strict one-sentence-per-line format with [E#] tags)
        INSUFFICIENT_EVIDENCE -> ABSTAIN (layer 3)     NOT ANSWERED: <part> -> half-answered
  -> citation parser -> verifier (numbers + lexical + NLI) -> SUPPORTED / WEAK / UNSUPPORTED
  -> result dict -> app/streamlit_app.py
```

## Where things live

| Concern | Module |
|---|---|
| Router interface, label derivation, JSON repair | `query_router/base.py` |
| Laya (zero-shot / fine-tuned), training | `query_router/laya_router.py`, `query_router/train_laya.py` |
| Other routers | `rule_router.py`, `embedding_router.py`, `nli_router.py`, `ollama_router.py`, `setfit_router.py` |
| Selection, fallback chain, ensemble | `query_router/registry.py` |
| Hybrid decomposition (separate from the classifier) | `query_router/decomposer.py` |
| Common Evidence Interface (8 core keys + extended metadata) | `integration/qa/evidence.py` |
| Retrieval backends (structured wrapper, FAISS+CE, optional ontology/doc-graph/ColPali) | `integration/qa/retrieval.py` |
| Chunk -> page mapping for TRAI PDFs (derived, with a measured overlap) | `integration/qa/page_map.py` |
| Abstention gate | `integration/qa/abstain.py` |
| Generation prompt | `integration/qa/generation.py` |
| Citations: parse, verify, provenance | `integration/qa/citations.py` |
| Orchestrator | `integration/qa/system.py` |
| Config + calibrated thresholds | `integration/qa/config.py`, `data/eval/system_calibration.json` |
| UI | `app/streamlit_app.py` |

## Design rules that the code enforces

* SQL/exact-match evidence and FAISS evidence are never score-combined; they meet only in RRF (ranks).
* Exact structured retrieval is never replaced by vector search; `structured/` is called, not modified.
* Ontology, document graph, structured KG and ColPali are config flags (`use_*`), off by default, so
  baseline / +ontology / +graph ablations stay possible. ColPali is availability-gated (GPU); the structured KG is
  present in the repository but is **not** wired into retrieval.
* Thresholds that look like magic numbers (router confidence, retrieval confidence) are calibrated on validation
  data only and recorded with their method in `data/eval/system_calibration.json`.
* The test sets (`router_test`, `abstention_test`) are read once, after all tuning.

## Data and evaluation entry points

```
python -m integration.eval.build_router_datasets       # data/eval/router_{train,val,test}.jsonl
python -m integration.eval.build_abstention_datasets   # data/eval/abstention_{val,test}.jsonl
python -m integration.eval.check_leakage               # data/eval/router_leakage_report.json
python -m integration.eval.evaluate_router --split val|test --routers ...
python -m integration.eval.calibrate_system --what retrieval | router --router laya_finetuned
python -m integration.eval.evaluate_abstention --split val|test
python -m integration.eval.evaluate_system --modes routed,structured,unstructured,hybrid,oracle
python -m integration.eval.evaluate_verifier
python -m demo.build_demo_questions
streamlit run app/streamlit_app.py
```

Results are written under `data/experiments/router_eval/` and `data/experiments/system_eval/`.
