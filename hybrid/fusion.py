"""
Conditional RRF fusion + the composed E13 candidate-to-context pipeline.

fuse_candidates  - weighted Reciprocal Rank Fusion of a vector list and a graph list
fuse_and_select  - query gate -> fuse -> dedupe -> top_k

The formula and k are the ones already validated in
knowledge_graph/graph_augmented_retrieval.py (reciprocal_rank_fusion, RRF_K = 60):
    score(d) = sum over lists of  weight / (k + rank),  rank 1-indexed.
Only ranks enter the sum, never raw scores (vector cosine and graph overlap
counts are on incompatible scales).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from knowledge_graph.graph_augmented_retrieval import RRF_K  # noqa: E402
from dedup import select_context  # noqa: E402
from query_gate import classify_query, graph_weight  # noqa: E402

VECTOR_WEIGHT = 1.0


def fuse_candidates(vector_candidates: list[dict], graph_candidates: list[dict],
                    graph_weight: float, k: int = RRF_K) -> list[dict]:
    """Weighted RRF over two rank-ordered lists (index 0 = rank 1).

    If graph_weight <= 0 the graph list is excluded entirely: graph-only
    candidates never appear. Output is sorted by fusion_score descending; ties
    are broken by best single-list rank, then by first appearance. Inputs are
    not mutated; output dicts are copies with "fusion_score" and
    "fusion_sources" added (the vector-list copy wins when a record is in both).
    """
    lists = [("vector", vector_candidates, VECTOR_WEIGHT)]
    if graph_weight > 0.0:
        lists.append(("graph", graph_candidates, graph_weight))

    entries: dict[str, dict] = {}  # insertion order == first appearance
    for name, candidates, weight in lists:
        for rank, cand in enumerate(candidates, start=1):
            entry = entries.setdefault(cand["record_id"], {
                "candidate": dict(cand), "score": 0.0, "sources": [], "best_rank": rank})
            entry["score"] += weight / (k + rank)
            entry["sources"].append(name)
            entry["best_rank"] = min(entry["best_rank"], rank)

    ordered = sorted(entries.values(), key=lambda e: (-e["score"], e["best_rank"]))
    out = []
    for e in ordered:
        cand = e["candidate"]
        cand["fusion_score"] = e["score"]
        cand["fusion_sources"] = e["sources"]
        out.append(cand)
    return out


def fuse_and_select(vector_candidates: list[dict], graph_candidates: list[dict],
                    question: str, top_k: int = 5) -> list[dict]:
    """Query gate -> weighted RRF -> dedupe by document -> top_k.

    select_context ranks by "score", which for the raw candidates is on
    incompatible scales. So the fused candidates are handed to it with
    score = fusion_score; the retriever's original value is kept as "original_score".
    """
    weight = graph_weight(classify_query(question))
    fused = fuse_candidates(vector_candidates, graph_candidates, weight)
    rescored = [{**c, "original_score": c["score"], "score": c["fusion_score"]} for c in fused]
    return select_context(rescored, top_k=top_k)
