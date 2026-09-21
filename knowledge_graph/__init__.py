"""NovaTel knowledge graph layer (Phase 1, deterministic).

Builds a metadata knowledge graph on top of the canonical documents produced by
the unstructured ingestion pipeline. Nothing in this package writes to, moves or
deletes anything outside ``knowledge_graph/output/``; the corpus is read-only.
"""

__all__ = [
    "entity_extractor",
    "relationship_extractor",
    "graph_builder",
    "evaluate_graph",
]
