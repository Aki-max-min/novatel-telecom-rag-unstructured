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


def controlled_rerank(question: str, candidates: list[dict], max_pool: int = 20,
                      top_k: int = 5, model=None) -> list[dict]:
    """Cap the pool to max_pool by fusion_score, CrossEncoder-rerank it, return top_k.

    `model` is optional dependency injection (anything with .predict(pairs));
    by default the CrossEncoder from Person A's setup is loaded lazily.
    Inputs are not mutated; earlier-stage fields (fusion_score, original_score) are kept.
    """
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

    reranked = [{**c, "rerank_score": float(s), "rerank_status": "crossencoder"}
                for c, s in zip(pool, scores)]
    reranked.sort(key=lambda c: c["rerank_score"], reverse=True)  # stable on ties
    return reranked[:top_k]
