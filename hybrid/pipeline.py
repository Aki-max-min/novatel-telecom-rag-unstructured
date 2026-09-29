"""
Complete E13 candidate pipeline, one call:
    query gate (Phase 2) -> weighted RRF fusion + dedup (Phase 3) -> controlled rerank (Phase 4)
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from fusion import fuse_and_select  # noqa: E402
from rerank import controlled_rerank  # noqa: E402


def run_hybrid_retrieval(question: str, vector_candidates: list[dict],
                         graph_candidates: list[dict], max_pool: int = 20,
                         top_k: int = 5, model=None) -> list[dict]:
    """Gate -> fuse -> dedupe (keeping up to max_pool) -> capped rerank -> top_k."""
    pool = fuse_and_select(vector_candidates, graph_candidates, question, top_k=max_pool)
    return controlled_rerank(question, pool, max_pool=max_pool, top_k=top_k, model=model)
