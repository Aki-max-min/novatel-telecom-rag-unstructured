"""
Controlled CrossEncoder rerank (E13 Phase 4).

"Controlled" = the pool sent to the CrossEncoder is HARD-CAPPED at max_pool,
taken from the top of the already-fused ranking. This encodes the Phase 3 KG
lesson: an uncontrolled, flooded candidate pool demoted good results.

Model and call convention are copied from Person A's ingestion code
(ingestion/hybrid_rerank_retrieval.py, rerank_retrieval.py):
    CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2").predict([(question, text), ...])

If sentence-transformers or the checkpoint is unavailable, this does NOT fake
scores: it warns loudly, returns the input order truncated to top_k, and marks
every item rerank_score=None / rerank_status="FALLBACK: ...".
"""

import sys
import warnings

RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_model = None
_model_error = None


def _load_model():
    """Return the CrossEncoder, or raise; a failed load is cached (no repeated downloads)."""
    global _model, _model_error
    if _model is not None:
        return _model
    if _model_error is not None:
        raise _model_error
    try:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(RERANKER_MODEL_NAME)
    except Exception as exc:  # ImportError, no network / checkpoint, etc.
        _model_error = exc
        raise
    return _model


def _pool_rank_key(candidate: dict) -> float:
    fs = candidate.get("fusion_score")
    return fs if fs is not None else candidate["score"]


RRF_K = 60  # same constant as hybrid/fusion.py

# Which rerank variant is used by default. Phase 8b: the pre-declared rule in
# docs/E13_phase8_rerank_selection_rule.md selected V1 (rrf_blend, w=1.0) and its validation check
# passed, so it is now the default; mode="override" is the old V0 behaviour.
DEFAULT_RERANK_MODE = "rrf_blend"
DEFAULT_BLEND_WEIGHT = 1.0
RERANK_MODES = ("override", "rrf_blend", "protect_graph")


def _order_by_mode(reranked, top_k, mode, blend_weight):
    """reranked: pool candidates in FUSION order, each with rank_fusion / rank_rerank / rerank_score."""
    by_rerank = sorted(reranked, key=lambda c: c["rank_rerank"])
    if mode == "override":  # V0
        return by_rerank[:top_k]
    if mode == "rrf_blend":  # V1 (w=1.0) / V2 (w=0.5)
        def blended(c):
            return 1.0 / (RRF_K + c["rank_fusion"]) + blend_weight / (RRF_K + c["rank_rerank"])
        for c in reranked:
            c["blend_score"] = blended(c)
        return sorted(reranked, key=lambda c: (-c["blend_score"], c["rank_rerank"], c["rank_fusion"]))[:top_k]
    if mode == "protect_graph":  # V3
        graph_only = [c for c in reranked if c.get("fusion_sources") == ["graph"] and c["rank_fusion"] <= 5]
        if not graph_only:
            return by_rerank[:top_k]
        reserved = min(graph_only, key=lambda c: c["rank_fusion"])
        rest = [c for c in by_rerank if c is not reserved][: max(top_k - 1, 0)]
        return sorted([reserved] + rest, key=lambda c: c["rank_rerank"])[:top_k]
    raise ValueError(f"unknown rerank mode {mode!r}; expected one of {RERANK_MODES}")


def controlled_rerank(question: str, candidates: list[dict], max_pool: int = 20,
                      top_k: int = 5, model=None, mode: str = None, blend_weight: float = None) -> list[dict]:
    """Cap the pool to max_pool by fusion_score, CrossEncoder-rerank it, return top_k.

    `model` is optional dependency injection (anything with .predict(pairs));
    by default the CrossEncoder from Person A's setup is loaded lazily.
    Inputs are not mutated; earlier-stage fields (fusion_score, original_score) are kept.

    `mode` selects the Phase 8b variant (default DEFAULT_RERANK_MODE): "override" = V0 (CrossEncoder
    order), "rrf_blend" = V1/V2 (fusion rank and rerank rank blended with RRF, weight `blend_weight`),
    "protect_graph" = V3 (one top_k slot reserved for the best graph-only candidate in the fusion top 5).
    """
    mode = DEFAULT_RERANK_MODE if mode is None else mode
    blend_weight = DEFAULT_BLEND_WEIGHT if blend_weight is None else blend_weight
    if mode not in RERANK_MODES:
        raise ValueError(f"unknown rerank mode {mode!r}; expected one of {RERANK_MODES}")
    pool = sorted(candidates, key=_pool_rank_key, reverse=True)[:max_pool]  # stable

    try:
        scorer = model if model is not None else _load_model()
        pairs = [(question, c["content"]) for c in pool]
        scores = scorer.predict(pairs) if pairs else []
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        msg = (f"CROSSENCODER RERANK NOT PERFORMED - FALLBACK to input order ({reason}). "
               f"Results below are NOT reranked.")
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        print(f"!!! {msg}", file=sys.stderr)
        return [{**c, "rerank_score": None, "rerank_status": f"FALLBACK: {reason}"}
                for c in candidates[:top_k]]

    reranked = [{**c, "rerank_score": float(s), "rerank_status": "crossencoder", "rerank_mode": mode,
                 "rank_fusion": i} for i, (c, s) in enumerate(zip(pool, scores), start=1)]
    order = sorted(reranked, key=lambda c: -c["rerank_score"])  # stable on ties
    for rank, c in enumerate(order, start=1):
        c["rank_rerank"] = rank
    return _order_by_mode(reranked, top_k, mode, blend_weight)
