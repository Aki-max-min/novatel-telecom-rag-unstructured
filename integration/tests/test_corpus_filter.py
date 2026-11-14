"""SciFact serving-time filter (on/off) and corpus labels. Fakes only, except the checks against the real metadata file."""

import json
from pathlib import Path

import numpy as np
import pytest

from integration.corpus_labels import (DATASET_NOVATEL, DATASET_SCIFACT, DATASET_TRAI, LABEL_NOVATEL, LABEL_SCIFACT, LABEL_TRAI,
                                       corpus_label, count_scifact, dataset_label, is_scifact)
from integration.qa.config import QAConfig
from integration.qa.evidence import CORPUS_LABEL, unstructured_evidence
from integration.qa.retrieval import UnstructuredBackend
from integration.rag.pipeline import UnstructuredSearcher
from integration.rag.rag_config import RagConfig

COMBINED_META = Path(__file__).resolve().parents[2] / "data" / "experiments" / "combined_retrieval" / "vectorstore" / "chunk_metadata.json"

NOVATEL = {"document_id": "FAQ_C01_001", "chunk_id": "FAQ_C01_001_chunk_000", "source_corpus": "synthetic", "category": "C01"}
TRAI = {"document_id": "PUBLIC_PDF_01_X", "chunk_id": "PUBLIC_PDF_01_X_chunk_000", "source_corpus": "public", "category": "PUBLIC_TELECOM"}
SCIFACT = {"document_id": "SCIFACT_102662", "chunk_id": "SCIFACT_102662_chunk_000", "source_corpus": "synthetic", "category": "SCIFACT",
           "source_authority": "BEIR SciFact"}


# ---- labels ---------------------------------------------------------------------------------------
def test_labels_for_the_three_corpora():
    assert (corpus_label(NOVATEL), dataset_label(NOVATEL)) == (LABEL_NOVATEL, DATASET_NOVATEL) == ("NovaTel Synthetic", "novatel_synthetic")
    assert (corpus_label(TRAI), dataset_label(TRAI)) == (LABEL_TRAI, DATASET_TRAI) == ("TRAI", "trai_public")
    assert (corpus_label(SCIFACT), dataset_label(SCIFACT)) == (LABEL_SCIFACT, DATASET_SCIFACT) == ("SciFact", "scifact_external")


def test_scifact_is_not_mislabelled_synthetic_even_though_source_corpus_says_so():
    assert SCIFACT["source_corpus"] == "synthetic" and is_scifact(SCIFACT) and dataset_label(SCIFACT) != DATASET_NOVATEL


def test_non_scifact_labels_are_exactly_what_the_old_rule_produced():
    old_rule = lambda r: "novatel_synthetic" if r.get("source_corpus") == "synthetic" else "trai_public"
    for rec in (NOVATEL, TRAI, {"document_id": "X"}, {"document_id": "Y", "source_corpus": "weird"}):
        assert dataset_label(rec) == old_rule(rec)


def test_evidence_carries_corpus_label_and_provenance_name():
    ev = unstructured_evidence(document_id="SCIFACT_1", chunk_id="c", dataset=DATASET_SCIFACT, category="", content="x", title="t",
                               retrieval_method="m", raw_scores={}, score=0.0, sub_query="q", origin="original")
    assert ev["metadata"]["corpus_label"] == "SciFact" and ev["metadata"]["provenance"]["corpus"] == "SciFact"
    assert CORPUS_LABEL[DATASET_TRAI] == "TRAI"


@pytest.mark.skipif(not COMBINED_META.exists(), reason="local combined index metadata not available")
def test_real_metadata_counts_and_that_all_scifact_signals_agree():
    meta = json.loads(COMBINED_META.read_text(encoding="utf-8"))
    by_id = {i for i, r in enumerate(meta) if is_scifact(r)}
    assert by_id == {i for i, r in enumerate(meta) if r.get("source_authority") == "BEIR SciFact"} \
        == {i for i, r in enumerate(meta) if r.get("category") == "SCIFACT"}
    counts = {}
    for r in meta:
        counts[corpus_label(r)] = counts.get(corpus_label(r), 0) + 1
    assert counts == {"NovaTel Synthetic": 258, "TRAI": 1162, "SciFact": 125} and count_scifact(meta) == 125


# ---- config defaults ---------------------------------------------------------------------------------
def test_filter_defaults_to_exclude_everywhere():
    assert QAConfig().exclude_scifact is True and RagConfig().exclude_scifact is True
    assert RagConfig(exclude_scifact=False).exclude_scifact is False


# ---- E14 searcher: filter on / off --------------------------------------------------------------------
class _Index:
    def __init__(self, order):
        self.order, self.ntotal = order, len(order)

    def search(self, qv, k):
        k = min(k, len(self.order))
        return np.array([[1.0 - 0.01 * i for i in range(k)]]), np.array([self.order[:k]])


class _Encoder:
    def encode(self, texts, **kw):
        return np.zeros((len(texts), 4), dtype="float32")


class _Reranker:
    def predict(self, pairs):          # higher score for earlier-listed text so CE order == FAISS order
        return [-i for i, _ in enumerate(pairs)]


def _records():
    # positions 0-2 are SciFact chunks that FAISS ranks first, then real chunks
    meta = [{**SCIFACT, "document_id": f"SCIFACT_{i}", "chunk_id": f"SCIFACT_{i}_c"} for i in range(3)]
    meta += [{**NOVATEL, "document_id": f"FAQ_{i}", "chunk_id": f"FAQ_{i}_c"} for i in range(6)]
    return meta


def _searcher(exclude):
    meta = _records()
    s = object.__new__(UnstructuredSearcher)
    s.exclude_scifact, s.metadata = exclude, meta
    s.index, s.embedding_model, s.reranker = _Index(list(range(len(meta)))), _Encoder(), _Reranker()
    s.n_scifact_chunks, s._text_cache = count_scifact(meta), {}
    s._load_text = lambda rec: "text " + rec["chunk_id"]
    return s


def test_e14_searcher_filter_on_drops_scifact_and_still_returns_k_real_candidates():
    out = _searcher(True).search("q", faiss_top_k=4, rerank_top_k=4)
    assert len(out) == 4 and not any(r["record_id"].startswith("SCIFACT") for r in out)
    assert all(r["dataset"] == DATASET_NOVATEL and r["metadata"]["corpus_label"] == "NovaTel Synthetic" for r in out)


def test_e14_searcher_filter_off_keeps_scifact_and_labels_it_correctly():
    out = _searcher(False).search("q", faiss_top_k=4, rerank_top_k=4)
    sf = [r for r in out if r["record_id"].startswith("SCIFACT")]
    assert len(sf) == 3 and all(r["dataset"] == DATASET_SCIFACT and r["metadata"]["corpus_label"] == "SciFact" for r in sf)


# ---- QA backend: filter on / off -------------------------------------------------------------------------
def _backend(exclude_flag_dummy=None):
    meta = _records()
    b = object.__new__(UnstructuredBackend)
    b.metadata, b.index, b.encoder, b.reranker = meta, _Index(list(range(len(meta)))), _Encoder(), _Reranker()
    b.n_scifact_chunks, b._text_cache = count_scifact(meta), {}
    b.chunks_by_doc = {}
    for i, m in enumerate(meta):
        b.chunks_by_doc.setdefault(m["document_id"], []).append(i)
    b._text = lambda rec: "text " + rec["chunk_id"]
    return b


def test_qa_backend_filter_on_and_off():
    cfg_on = QAConfig(faiss_depth=4, top_k_unstructured=4, exclude_scifact=True)
    ev_on, diag_on = _backend().search("q", cfg_on)
    assert len(ev_on) == 4 and not any(e["metadata"]["document_id"].startswith("SCIFACT") for e in ev_on)
    cfg_off = QAConfig(faiss_depth=4, top_k_unstructured=4, exclude_scifact=False)
    ev_off, _ = _backend().search("q", cfg_off)
    sf = [e for e in ev_off if e["metadata"]["document_id"].startswith("SCIFACT")]
    assert len(sf) == 3 and all(e["dataset"] == DATASET_SCIFACT and e["metadata"]["corpus_label"] == "SciFact" for e in sf)
