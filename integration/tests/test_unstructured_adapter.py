"""
Tests for integration/unstructured_adapter.py. Uses a small inline fixture
mirroring the real candidate shape produced by
ingestion/hybrid_rerank_retrieval.py -- no large file dependency.
"""

import copy
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from integration.unstructured_adapter import to_common_result, REQUIRED_SCHEMA_FIELDS


def make_candidate(**overrides):
    candidate = {
        "document_id": "FAQ_C01_001",
        "chunk_id": "FAQ_C01_001_chunk_000",
        "title": "How do I update the mobile number registered on my account?",
        "category": "C01",
        "department": "Customer Care",
        "customer_scope": "prepaid",
        "related_ids": ["KB_C01_overview"],
        "tags": ["account", "c01"],
        "text": "To update your registered mobile number, visit a NovaTel outlet with valid ID.",
        "faiss_score": 0.6496,
        "crossencoder_score": 3.21,
        "title_score": 0.4,
        "category_score": 1.0,
        "hybrid_score": 0.712,
    }
    candidate.update(overrides)
    return candidate


def test_output_has_exactly_the_required_schema_keys():
    candidate = make_candidate()
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="hybrid_rerank"
    )
    assert set(result.keys()) == REQUIRED_SCHEMA_FIELDS


def test_core_field_mapping():
    candidate = make_candidate()
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="hybrid_rerank"
    )
    assert result["source"] == "unstructured"
    assert result["record_id"] == candidate["chunk_id"]
    assert result["dataset"] == "novatel_synthetic"
    assert result["category"] == candidate["category"]
    assert result["retrieval_method"] == "hybrid_rerank"
    assert result["content"] == candidate["text"]


def test_record_id_is_stringified():
    candidate = make_candidate(chunk_id=12345)
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="faiss"
    )
    assert result["record_id"] == "12345"
    assert isinstance(result["record_id"], str)


def test_score_defaults_to_hybrid_score():
    candidate = make_candidate()
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="hybrid_rerank"
    )
    assert result["score"] == pytest.approx(candidate["hybrid_score"])


def test_score_falls_back_to_faiss_score_when_no_hybrid_score():
    candidate = make_candidate()
    del candidate["hybrid_score"]
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="faiss"
    )
    assert result["score"] == pytest.approx(candidate["faiss_score"])


def test_score_field_overrides_fallback_order():
    candidate = make_candidate()
    result = to_common_result(
        candidate,
        dataset="novatel_synthetic",
        retrieval_method="metadata_aware",
        score_field="category_score",
    )
    assert result["score"] == pytest.approx(candidate["category_score"])


def test_missing_explicit_score_field_raises_key_error():
    candidate = make_candidate()
    with pytest.raises(KeyError):
        to_common_result(
            candidate,
            dataset="novatel_synthetic",
            retrieval_method="faiss",
            score_field="nonexistent_score",
        )


def test_missing_all_score_sources_raises_key_error():
    candidate = make_candidate()
    del candidate["hybrid_score"]
    del candidate["faiss_score"]
    with pytest.raises(KeyError):
        to_common_result(
            candidate, dataset="novatel_synthetic", retrieval_method="faiss"
        )


@pytest.mark.parametrize("missing_field", ["chunk_id", "document_id", "category", "text"])
def test_missing_required_field_raises_named_key_error(missing_field):
    candidate = make_candidate()
    del candidate[missing_field]
    with pytest.raises(KeyError) as excinfo:
        to_common_result(
            candidate, dataset="novatel_synthetic", retrieval_method="faiss"
        )
    assert missing_field in str(excinfo.value)


def test_all_component_scores_preserved_verbatim():
    candidate = make_candidate()
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="hybrid_rerank"
    )
    component_scores = result["metadata"]["component_scores"]
    assert component_scores == {
        "faiss_score": candidate["faiss_score"],
        "crossencoder_score": candidate["crossencoder_score"],
        "title_score": candidate["title_score"],
        "category_score": candidate["category_score"],
        "hybrid_score": candidate["hybrid_score"],
    }


def test_missing_component_scores_become_none():
    candidate = make_candidate()
    del candidate["crossencoder_score"]
    del candidate["title_score"]
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="faiss"
    )
    component_scores = result["metadata"]["component_scores"]
    assert component_scores["crossencoder_score"] is None
    assert component_scores["title_score"] is None
    assert component_scores["faiss_score"] == candidate["faiss_score"]


def test_provenance_document_id_and_chunk_id_preserved():
    candidate = make_candidate()
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="faiss"
    )
    provenance = result["metadata"]["provenance"]
    assert provenance["document_id"] == candidate["document_id"]
    assert provenance["chunk_id"] == candidate["chunk_id"]


def test_nullable_provenance_fields_are_none_not_empty_string():
    candidate = make_candidate()
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="faiss"
    )
    provenance = result["metadata"]["provenance"]
    for field in ("page_number", "entity_id", "ontology_concept_ids", "relationship_ids"):
        assert provenance[field] is None


def test_remaining_fields_preserved_in_metadata():
    candidate = make_candidate()
    result = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="faiss"
    )
    metadata = result["metadata"]
    assert metadata["title"] == candidate["title"]
    assert metadata["department"] == candidate["department"]
    assert metadata["customer_scope"] == candidate["customer_scope"]
    assert metadata["related_ids"] == candidate["related_ids"]
    assert metadata["tags"] == candidate["tags"]


def test_input_candidate_is_not_mutated():
    candidate = make_candidate()
    original = copy.deepcopy(candidate)
    to_common_result(candidate, dataset="novatel_synthetic", retrieval_method="hybrid_rerank")
    assert candidate == original


def test_public_corpus_category_is_passed_through_raw_not_remapped():
    candidate = make_candidate(
        document_id="PUBLIC_PDF_01_TELECOM_CONSUMERS_PROTECTION",
        chunk_id="PUBLIC_PDF_01_TELECOM_CONSUMERS_PROTECTION_chunk_000",
        category="PUBLIC_TELECOM",
    )
    result = to_common_result(
        candidate, dataset="trai_public", retrieval_method="faiss"
    )
    assert result["category"] == "PUBLIC_TELECOM"
    assert result["dataset"] == "trai_public"


def test_call_is_deterministic():
    candidate = make_candidate()
    result_a = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="hybrid_rerank"
    )
    result_b = to_common_result(
        candidate, dataset="novatel_synthetic", retrieval_method="hybrid_rerank"
    )
    assert result_a == result_b
