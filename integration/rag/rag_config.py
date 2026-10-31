"""
Named configuration for the E14 RAG pipeline (integration/rag/pipeline.py).

Every field has a default that reproduces the E14a behaviour exactly, so code that builds `RagPipeline()` without a
config gets the same prompts as before these options existed (checked by integration/tests/test_rag_defaults_identical.py).

Context budget
    budget_db_blocks / budget_doc_blocks
        None / None (default)  one budget of DEFAULT_TOP_N (6) blocks shared by both sources, as in E14a.
        set both               each source keeps its own best N blocks, in fused order (the E14b fix, see
                               integration/rag/context_builder.py).
    Arm "B2" of the final measurement uses `RagConfig.b2()`: 5 database blocks + 3 document blocks. These two numbers
    were chosen from the E14a failure analysis (data/experiments/benchmark_base_vs_rag/failure_diagnostic.md: the
    4 structured failures needed 5 database rows and only 3 survived the shared budget; 3 document blocks is what the
    shared budget left to documents) on the SAME 22 questions that are later evaluated. They are therefore fixed
    and must not be tuned any further.

Semantic layer
    semantic_layer = False (default)   the original retrieval path.
    semantic_layer = True              integration/rag/semantic_layer.py (ontology term normalisation + one-hop
                                       document-graph expansion). Needs knowledge_graph/output/graph.json.

SciFact
    exclude_scifact = True (default)   SciFact chunks (an external benchmark that was built into the combined index) are
                                       dropped at serving time. Set False only to reproduce results computed on the
                                       unfiltered index.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

B2_DB_BLOCKS = 5
B2_DOC_BLOCKS = 3


@dataclass(frozen=True)
class RagConfig:
    budget_db_blocks: int | None = None
    budget_doc_blocks: int | None = None
    semantic_layer: bool = False
    semantic_max_chunks_per_doc: int = 2   # chunks added to the candidate pool per graph document (documents have <= 3 chunks)
    exclude_scifact: bool = True

    def __post_init__(self) -> None:
        if (self.budget_db_blocks is None) != (self.budget_doc_blocks is None):
            raise ValueError("budget_db_blocks and budget_doc_blocks must be set together (or both left as None)")
        for name in ("budget_db_blocks", "budget_doc_blocks"):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, int) or v < 0):
                raise ValueError(f"{name} must be a non-negative integer, got {v!r}")
        if self.semantic_max_chunks_per_doc < 1:
            raise ValueError("semantic_max_chunks_per_doc must be >= 1")

    @property
    def per_source_budget(self) -> dict | None:
        """The dict build_context() expects, or None for the shared-budget behaviour."""
        if self.budget_db_blocks is None:
            return None
        return {"structured": self.budget_db_blocks, "unstructured": self.budget_doc_blocks}

    @classmethod
    def b2(cls, **overrides) -> "RagConfig":
        """Arm B2: per-source context budget (5 database + 3 document blocks, see the module docstring)."""
        return cls(budget_db_blocks=B2_DB_BLOCKS, budget_doc_blocks=B2_DOC_BLOCKS, **overrides)

    def as_dict(self) -> dict:
        return asdict(self)
