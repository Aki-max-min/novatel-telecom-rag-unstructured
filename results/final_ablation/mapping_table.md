# Arm -> exact settings (printed from `eval/final_ablation/harness_fa.py` before any run)

Flags are the real names in the harness (`eval/perf_report/harness.py` arm_settings keys, `integration/rag/rag_config.RagConfig`,
`knowledge_graph.graph_augmented_retrieval.graph_expand` keyword arguments, `integration/rag/semantic_layer.SemanticLayer(use_related_links=...)`).
Nothing here is invented; `check_layer` raises before a generation if the layer object disagrees with this table.

| arm | retrieval | rag_config budget (db, doc) | layer class | graph_expand kwargs | use_related_links | ontology terms in FAISS query | router | source |
|---|---|---|---|---|---|---|---|---|
| A | False | n/a | None | n/a | n/a | n/a | off | generated |
| B | True | (None, None) = shared 6 blocks | None | n/a | n/a | no | off | generated |
| B2 | True | (5, 3) | None | n/a | n/a | no | off | reused (kg_hardening_eval) |
| R | True | (5, 3) | None | n/a | n/a | no | **on** (auto chain, threshold 0.5) | generated |
| O | True | (5, 3) | `OntologyOnlyLayer` (v3; neighbours -> []) | none (graph list off) | False | **yes** (concept hint -> canonical terms) | off | generated |
| G0 | True | (5, 3) | `GraphOnlyLayer` = v3 `DocGraphOnlyLayer` | none (legacy) | False | no (gate weight kept) | off | generated |
| G1 | True | (5, 3) | `GraphOnlyLayer` | `hub_fraction=0.05, specificity=True, max_documents=3` | False | no (gate weight kept) | off | generated |
| G1L | True | (5, 3) | `GraphOnlyLayer` | `hub_fraction=0.05, specificity=True, max_documents=3` | **True** | no (gate weight kept) | off | generated |
| C_V0 | True | (5, 3) | `HardenedGraphLayer` = full `SemanticLayer` | none (legacy) | False | yes | on | reused |
| C_V1 | True | (5, 3) | full `SemanticLayer` | `hub_fraction=0.05, specificity=True, max_documents=3` | False | yes | on | reused |
| C_V1_links | True | (5, 3) | full `SemanticLayer` | `hub_fraction=0.05, specificity=True, max_documents=3` | True | yes | on | reused |
| structured KG | - | - | - | - | - | - | - | not run (not wired into retrieval) |

Correspondence with the v3 arms: A = v3 "A", B = v3 "B", B2 = v3 "B2", R = v3 "router", O = v3 "ontology" (+ `use_related_links=False`, a no-op in v3
because 0 links resolved), G0 = v3 "docgraph" (+ `use_related_links=False`), C_V0 = v3 "C" (+ `use_related_links=False`).

Settings the harness prints at import (verified 2026-11-11, HEAD 6956902):

```text
A           retrieval=False budget=(None, None) layer=None router=False opts=None links=None onto_terms=None
B           retrieval=True  budget=(None, None) layer=None router=False opts=None links=None onto_terms=None
B2          retrieval=True  budget=(5, 3) layer=None router=False opts=None links=None
R           retrieval=True  budget=(5, 3) layer=None router=True  opts=None links=None onto_terms=None
O           retrieval=True  budget=(5, 3) layer=O    router=False opts=None links=False onto_terms=True
G0          retrieval=True  budget=(5, 3) layer=G0   router=False opts={} links=False onto_terms=False
G1          retrieval=True  budget=(5, 3) layer=G1   router=False opts={'hub_fraction': 0.05, 'specificity': True, 'max_documents': 3} links=False onto_terms=False
G1L         retrieval=True  budget=(5, 3) layer=G1L  router=False opts={'hub_fraction': 0.05, 'specificity': True, 'max_documents': 3} links=True  onto_terms=False
C_V0        retrieval=True  budget=(5, 3) layer=C_V0 router=True  opts={} links=False
C_V1        retrieval=True  budget=(5, 3) layer=C_V1 router=True  opts={'hub_fraction': 0.05, 'specificity': True, 'max_documents': 3} links=False
C_V1_links  retrieval=True  budget=(5, 3) layer=C_V1_links router=True opts={'hub_fraction': 0.05, 'specificity': True, 'max_documents': 3} links=True
O normalise("Why is my latest postpaid bill higher than usual?") -> "... higher than usual? Billing & Invoices. Billing & Invoices."
G0 normalise(same)                                                -> unchanged question
```

Shared by every arm: `qwen2.5:7b-instruct` Q4_K_M, temperature 0, seed 42, E14a prompts, SciFact filter ON, answer cache OFF, FAISS top-10 +
CrossEncoder, RRF k=60, GRAPH_SEEDS 5, GRAPH_CANDIDATES 20, semantic_max_chunks_per_doc 2, 3 runs, the 42 questions and gold of
`eval/perf_report/questions.jsonl`.
