"""
Reciprocal Rank Fusion (RRF) over Common-Result-Schema candidate lists.

Rank-based only: structured's SQL relevance and unstructured's FAISS/
CrossEncoder scores are never added together, never compared numerically.
Each source contributes only its own rank position within its own list.
"""

RRF_K = 60


def _identity(result: dict):
    """Composite key so a structured record and an unstructured chunk can
    never collide even if their record_id strings happen to match."""
    return (result["source"], result["dataset"], result["record_id"])


def reciprocal_rank_fusion(*ranked_lists, k: int = RRF_K) -> list[dict]:
    """
    ranked_lists: any number of Common-Schema result lists, each already
        ordered best-first by its own source.
    Returns: a single list of the original result dicts, re-ordered by
        summed reciprocal rank, best first. Each input result appears once
        (if a candidate appears in more than one list under the same
        identity, its rrf_score accumulates but the first-seen dict is kept).
    """
    rrf_scores: dict[tuple, float] = {}
    first_seen: dict[tuple, dict] = {}

    for ranked_list in ranked_lists:
        for rank, result in enumerate(ranked_list, start=1):
            key = _identity(result)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in first_seen:
                first_seen[key] = result

    ordered_keys = sorted(rrf_scores, key=lambda key: rrf_scores[key], reverse=True)

    fused = []
    for key in ordered_keys:
        result = dict(first_seen[key])
        result["fusion"] = {"method": "rrf", "k": k, "rrf_score": rrf_scores[key]}
        fused.append(result)
    return fused
