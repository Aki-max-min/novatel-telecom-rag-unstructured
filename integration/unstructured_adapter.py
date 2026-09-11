"""
Adapts unstructured retrieval candidates (as produced by
ingestion/hybrid_rerank_retrieval.py and its relatives) into the same
Common Result Schema the structured side emits from
structured/retriever.py::_wrap_result. Pure, side-effect-free, no
dependency on structured/ or ingestion/ code -- the 8-field contract is
matched by convention only.

Two things are NOT derivable from the candidate dict itself and must be
supplied by the caller, confirmed by inspecting real data:

- dataset (corpus label): document_id has no shared corpus prefix.
  Synthetic-corpus IDs are type-prefixed (e.g. "FAQ_C01_001", "TRX_002",
  "Policy_C02_plan_lifecycle"); public-corpus IDs use a different, also
  type-prefixed scheme (e.g. "PUBLIC_PDF_01_TELECOM_CONSUMERS_PROTECTION").
  There is no generic "corpus" field to read this from.

- category vocabulary is NOT uniform across corpora: the synthetic corpus
  uses the same C01-C29 tags as the structured side (data/vectorstore/
  chunk_metadata.json), but the public-PDF corpus stores a single constant
  "PUBLIC_TELECOM" in its category field (data/experiments/public_pdfs/
  vectorstore/chunk_metadata_enriched.json) -- not a C01-C29 code. category
  is therefore passed through raw and unmapped here; do not assume it is
  comparable across corpora.
"""

REQUIRED_SCHEMA_FIELDS = {
    "source", "record_id", "dataset", "category",
    "score", "retrieval_method", "content", "metadata",
}

_COMPONENT_SCORE_FIELDS = (
    "faiss_score",
    "crossencoder_score",
    "title_score",
    "category_score",
    "hybrid_score",
)

_PROVENANCE_FROM_CANDIDATE = ("document_id", "chunk_id")

_NULLABLE_PROVENANCE_FIELDS = (
    "page_number",
    "entity_id",
    "ontology_concept_ids",
    "relationship_ids",
)

_CONSUMED_FIELDS = set(_COMPONENT_SCORE_FIELDS) | {
    "document_id", "chunk_id", "category", "text",
}


def to_common_result(candidate, *, dataset, retrieval_method, score_field=None):
    """
    Map one unstructured retrieval candidate dict into the Common Result
    Schema (the same 8 top-level keys structured/retriever.py emits).

    candidate: dict as produced during unstructured retrieval/reranking.
        Required keys: chunk_id, document_id, category, text.
        Optional score keys: faiss_score, crossencoder_score, title_score,
        category_score, hybrid_score.
    dataset: corpus label supplied by the caller (e.g. "novatel_synthetic",
        "trai_public"). Not derived from document_id -- see module docstring.
    retrieval_method: label for how this candidate was produced (e.g.
        "faiss", "metadata_aware", "hybrid_rerank").
    score_field: if given, candidate[score_field] is used as the schema
        `score`. Otherwise falls back to candidate["hybrid_score"], then
        candidate["faiss_score"].

    Returns a new dict; does not mutate `candidate`.
    """
    working = dict(candidate)

    for required_field in ("chunk_id", "document_id", "category", "text"):
        if required_field not in working:
            raise KeyError(
                f"Unstructured candidate is missing required field: '{required_field}'"
            )

    if score_field is not None:
        if score_field not in working:
            raise KeyError(
                f"Unstructured candidate is missing requested score_field: '{score_field}'"
            )
        score = working[score_field]
    elif "hybrid_score" in working:
        score = working["hybrid_score"]
    elif "faiss_score" in working:
        score = working["faiss_score"]
    else:
        raise KeyError(
            "Unstructured candidate has no usable score: expected "
            "'hybrid_score' or 'faiss_score' to be present, or an "
            "explicit score_field to be passed."
        )

    component_scores = {
        field: working.get(field) for field in _COMPONENT_SCORE_FIELDS
    }

    provenance = {field: working.get(field) for field in _PROVENANCE_FROM_CANDIDATE}
    for field in _NULLABLE_PROVENANCE_FIELDS:
        provenance[field] = None

    metadata = {
        key: value for key, value in working.items() if key not in _CONSUMED_FIELDS
    }
    metadata["component_scores"] = component_scores
    metadata["provenance"] = provenance

    return {
        "source": "unstructured",
        "record_id": str(working["chunk_id"]),
        "dataset": dataset,
        "category": working["category"],
        "score": float(score),
        "retrieval_method": retrieval_method,
        "content": working["text"],
        "metadata": metadata,
    }
