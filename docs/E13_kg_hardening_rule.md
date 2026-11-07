# E13 KG hardening - pre-declared rule (committed BEFORE any code or experiment)

Background (verified before this task): Person A's review measured graph expansion costing about 15 points
(82.9% -> 67.9% correctness on 42 questions). Cause: `graph_expand` in
`knowledge_graph/graph_augmented_retrieval.py` counts every shared concept equally and `DEFAULT_BRIDGES` includes hub concepts.
Concept document frequency on the 148 documents: OTP 47, Complaint Registration 45, My NovaTel App 38, Self-Care Portal 33,
KYC Verification 30, tag how-to 21. A simulation (each document as seed) showed 72% of graph candidates (1732 of 2393) share ONLY
hub concepts (hub = appears in more than 10% of documents); same-category precision@5 was 0.38 for the current rule, 0.68 with
the hub cut, 0.72 with specific labels only (Service, VerificationMethod, Tag). That precision is only a rough proxy for relevance.

## Variants of graph_expand

- **V0 legacy**: the exact current behaviour.
- **V1 hub cut**: drop concepts whose document frequency is greater than `hub_fraction` x (number of documents),
  `hub_fraction` in {0.05, 0.10, 0.20}.
- **V2** = V1 + specificity weighting (weight `log(N/df)` per shared concept instead of 1) + `max_documents` in {3, 5, 10}.
- **V3** = V2 restricted to bridge labels Service, VerificationMethod, Tag.

Grid: V1 3 cells + V2 9 cells + V3 9 cells = 21 cells, plus V0. **22 configurations are compared.**

## Dev sets and metric

Dev sets (NOT Person A's 42 questions, which must not be used for tuning): the main 29, mini 9 and validation 14 sets already
used by `hybrid/evaluate_hybrid.py` and `hybrid/evaluate_rerank_variants.py`, and `knowledge_graph/graph_benchmark.json` via
`knowledge_graph/evaluate_graph_rag.py`.

Baseline = the same pipeline with the graph list disabled (vector + CrossEncoder rerank).
Metric = document-level Recall@3; also report R@1, R@5, MRR@5.

For each configuration, per question: **win** = the baseline missed the expected document in the top 3 and the configuration hits it;
**loss** = the reverse.

## Selection

Among the cells, choose the highest pooled (wins - losses); ties are broken by smaller `max_documents`, then larger `hub_fraction`.

## Adoption rule

The selected cell becomes the graph default **ONLY IF** pooled wins - losses >= +2 **AND** pooled losses <= 2 **AND** no single
dev set has net < -1. Otherwise the graph stays OFF by default and the report states a negative result with this table.
Selection and adoption use dev sets only.

## What the mechanism check is not

The 5-incident-link check in Part 3 is a **MECHANISM check** (only 5 such pairs exist) and does not count as evidence of
generalisation. The final unbiased run is Person A's single run on her 42 questions.
