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
from dedup import document_key, select_context  # noqa: E402
from query_gate import classify_query, graph_weight  # noqa: E402

VECTOR_WEIGHT = 1.0


def fuse_candidates(vector_candidates: list[dict], graph_candidates: list[dict],
                    graph_weight: float, k: int = RRF_K) -> list[dict]:
    """Document-level weighted RRF over two rank-ordered lists (index 0 = rank 1).

    Candidates are keyed by document (dedup.document_key: metadata document_id,
    else record_id minus "_chunk_NNN", else record_id), so MAN_APP_001_chunk_000
    in the vector list and bare MAN_APP_001 in the graph list are one document.
    Within each list a document's rank is its BEST (earliest) chunk's rank and it
    contributes once: counting every chunk would favour long, many-chunk documents.
    score(doc) = sum over lists of weight / (k + rank), the same formula and k as
    knowledge_graph/graph_augmented_retrieval.py.

    If graph_weight <= 0 the graph list is excluded entirely: graph-only documents
    never appear. Output is sorted by fusion_score descending; ties are broken by
    best single-list rank, then by first appearance. Inputs are not mutated; output
    dicts are copies with "fusion_score", "fusion_sources" and "fusion_doc_key" added.
    The representative candidate for a document is its highest-original-score
    vector chunk if it has one, else its best-ranked graph candidate.
    """
    lists = [("vector", vector_candidates, VECTOR_WEIGHT)]
    if graph_weight > 0.0:
        lists.append(("graph", graph_candidates, graph_weight))

    docs: dict[str, dict] = {}  # insertion order == first appearance
    for name, candidates, weight in lists:
        seen_in_list: set[str] = set()
        for rank, cand in enumerate(candidates, start=1):
            key = document_key(cand)
            entry = docs.setdefault(key, {"score": 0.0, "sources": [], "best_rank": rank,
                                          "vector_rep": None, "graph_rep": None})
            if name == "vector":
                rep = entry["vector_rep"]
                if rep is None or cand["score"] > rep["score"]:
                    entry["vector_rep"] = cand
            elif entry["graph_rep"] is None:
                entry["graph_rep"] = cand
            if key in seen_in_list:
                continue  # later chunk of a document already ranked in this list
            seen_in_list.add(key)
            entry["score"] += weight / (k + rank)
            entry["sources"].append(name)
            entry["best_rank"] = min(entry["best_rank"], rank)

    ordered = sorted(docs.items(), key=lambda kv: (-kv[1]["score"], kv[1]["best_rank"]))
    out = []
    for key, e in ordered:
        cand = dict(e["vector_rep"] or e["graph_rep"])
        cand["fusion_score"] = e["score"]
        cand["fusion_sources"] = e["sources"]
        cand["fusion_doc_key"] = key
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
