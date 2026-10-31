"""Regression: with default settings the E14 pipeline assembles EXACTLY the prompt evidence that git HEAD bf41951 did.

integration/tests/fixtures/golden_prompts_bf41951.json was produced by the unmodified HEAD code (retrieval + fusion +
context assembly, no LLM) for the 22 E14a questions. This test rebuilds the same thing with the current code and default
RagConfig and compares sha256 of the context text and the evidence ids. It needs the local FAISS index, the SQLite DB and the
cached embedding models; it is skipped (not failed) when they are absent.
"""

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "integration" / "tests" / "fixtures" / "golden_prompts_bf41951.json"
INDEX = ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore" / "faiss.index"
DB = ROOT / "data" / "processed" / "structured" / "novatel_structured.db"


def test_default_config_means_original_behaviour():
    from integration.rag.rag_config import RagConfig
    cfg = RagConfig()
    assert cfg.per_source_budget is None and cfg.semantic_layer is False


@pytest.mark.skipif(not (INDEX.exists() and DB.exists() and GOLDEN.exists()), reason="local index / DB / golden file not available")
def test_default_prompts_identical_to_head():
    from integration.rag.context_builder import DEFAULT_TOP_N, build_context
    from integration.rag.fuse import reciprocal_rank_fusion
    from integration.rag.pipeline import StructuredSearchAdapter, UnstructuredSearcher

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert golden["git_head"].startswith("bf41951") and golden["top_n"] == DEFAULT_TOP_N
    structured, unstructured = StructuredSearchAdapter(), UnstructuredSearcher()
    try:
        mismatches = []
        for row in golden["prompts"]:
            ctx = build_context(reciprocal_rank_fusion(structured.search(row["question"]), unstructured.search(row["question"])),
                                top_n=DEFAULT_TOP_N)
            sha = hashlib.sha256(ctx["context_text"].encode("utf-8")).hexdigest()
            ids = [list(x) for x in ((e["source"], e["record_id"]) for e in ctx["evidence"])]
            if sha != row["context_sha256"] or ids != [list(x) for x in row["evidence_ids"]]:
                mismatches.append(row["query_id"])
        assert not mismatches, f"prompt evidence changed for: {mismatches}"
    finally:
        structured.close()
