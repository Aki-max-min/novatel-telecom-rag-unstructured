"""
Evidence deduplication + context selection for the E13 hybrid layer.

Candidates follow the Common Result Schema:
{source, record_id, dataset, category, score, retrieval_method, content, metadata}
"""

import re

_CHUNK_SUFFIX = re.compile(r"_chunk_\d+$")


def document_key(candidate: dict) -> str:
    """Document-level key: metadata['document_id'], else record_id minus '_chunk_NNN', else record_id."""
    doc_id = (candidate.get("metadata") or {}).get("document_id")
    if doc_id:
        return str(doc_id)
    return _CHUNK_SUFFIX.sub("", str(candidate["record_id"]))


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    """Keep the highest-scoring candidate per document.

    Stable: kept items are ordered by the first occurrence of their document.
    Ties on score keep the earliest candidate. Input is not mutated.
    """
    best: dict[str, dict] = {}  # insertion order == first-occurrence order
    for cand in candidates:
        key = document_key(cand)
        if key not in best or cand["score"] > best[key]["score"]:
            best[key] = cand
    return list(best.values())


def select_context(candidates: list[dict], top_k: int = 5) -> list[dict]:
    """Dedupe, then return the top_k candidates by score (descending)."""
    deduped = dedupe_candidates(candidates)
    return sorted(deduped, key=lambda c: c["score"], reverse=True)[:top_k]
