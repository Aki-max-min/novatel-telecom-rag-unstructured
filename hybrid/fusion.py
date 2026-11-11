"""
Append-only candidate fusion + the composed E13 candidate-to-context pipeline.

fuse_candidates  - vector order kept verbatim; graph/link documents join the POOL, never the ranking
fuse_and_select  - query gate -> fuse -> dedupe -> top_k

THE GRAPH IS A CANDIDATE SOURCE, NEVER A RANKER. The previous design (weighted RRF: every candidate scored
1/(k+rank) plus weight/(k+graph_rank) for graph members) let graph membership outrank relevance, because the base
scores are almost flat: rank 1 = 0.01639 vs rank 2 = 0.01613, while the bonus was 0.0025 at weight 0.15 and 0.0082
at weight 0.5 - so a graph member passed the rank-1 document from vector rank 11 (weight 0.15) or rank 61 (0.5).
On Person A's v3 runs all 44 documents ranked above a missed gold document were graph-list members, and gold@1 fell
from 19/25 to 10/25 on the graph-active questions. Relevance is decided by the CrossEncoder rerank stage only.
See docs/E13_graph_fusion_fix.md.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from knowledge_graph.graph_augmented_retrieval import RRF_K  # noqa: E402
from dedup import document_key, select_context  # noqa: E402
from query_gate import classify_query, graph_weight  # noqa: E402

VECTOR_WEIGHT = 1.0  # kept for compatibility; the vector list defines the order outright


def fuse_candidates(vector_candidates: list[dict], graph_candidates: list[dict],
                    graph_weight: float, k: int = RRF_K, *, link_candidates: list[dict] = None,
                    link_weight: float = 0.0) -> list[dict]:
    """Append-only merge of the vector list with the graph and link candidate lists.

    Candidates are keyed by document (dedup.document_key: metadata document_id, else record_id minus
    "_chunk_NNN", else record_id), each document appearing once. Order:

      1. the VECTOR documents, exactly in vector order - graph or link membership never moves them;
      2. then link-only documents (resolved RELATED_TO neighbours), in link-list order;
      3. then graph-only documents (concept candidates), in graph-list order.

    ``graph_weight`` and ``link_weight`` are pure on/off switches (> 0 includes the list, <= 0 excludes it);
    their magnitude no longer affects anything. Membership is still recorded in ``fusion_sources`` for the trace.

    ``fusion_score`` is 1/(k + position) over the final order - strictly decreasing, so later stages that sort
    by it (select_context, the rerank blend) preserve this order. Inputs are not mutated; output dicts are
    copies with "fusion_score", "fusion_sources" and "fusion_doc_key" added. The representative candidate for a
    document is its highest-original-score vector chunk if it has one, else its first graph/link candidate.
    """
    lists = [("vector", vector_candidates)]
    if link_candidates and link_weight > 0.0:
        lists.append(("links", link_candidates))
    if graph_weight > 0.0:
        lists.append(("graph", graph_candidates))

    order: list[str] = []
    docs: dict[str, dict] = {}
    for name, candidates in lists:
        seen_in_list: set[str] = set()
        for cand in candidates:
            key = document_key(cand)
            entry = docs.setdefault(key, {"sources": [], "vector_rep": None, "other_rep": None})
            if name == "vector":
                rep = entry["vector_rep"]
                if rep is None or cand["score"] > rep["score"]:
                    entry["vector_rep"] = cand
            elif entry["other_rep"] is None:
                entry["other_rep"] = cand
            if key in seen_in_list:
                continue  # later chunk of a document already ranked in this list
            seen_in_list.add(key)
            entry["sources"].append(name)
            if key not in order:
                order.append(key)  # vector order first, then links, then graph - never reordered

    out = []
    for position, key in enumerate(order, start=1):
        e = docs[key]
        cand = dict(e["vector_rep"] or e["other_rep"])
        cand["fusion_score"] = 1.0 / (k + position)
        cand["fusion_sources"] = e["sources"]
        cand["fusion_doc_key"] = key
        out.append(cand)
    return out


def fuse_and_select(vector_candidates: list[dict], graph_candidates: list[dict],
                    question: str, top_k: int = 5, *, link_candidates: list[dict] = None,
                    link_weight: float = 0.0) -> list[dict]:
    """Query gate -> weighted RRF -> dedupe by document -> top_k.

    select_context ranks by "score", which for the raw candidates is on
    incompatible scales. So the fused candidates are handed to it with
    score = fusion_score; the retriever's original value is kept as "original_score".
    """
    weight = graph_weight(classify_query(question))
    fused = fuse_candidates(vector_candidates, graph_candidates, weight,
                            link_candidates=link_candidates, link_weight=link_weight)
    rescored = [{**c, "original_score": c["score"], "score": c["fusion_score"]} for c in fused]
    return select_context(rescored, top_k=top_k)
