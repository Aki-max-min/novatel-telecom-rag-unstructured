"""Per-source context budget and the semantic-layer hook: configuration, block counts, on/off, dangling links. No models."""

import itertools
import logging

import pytest

from integration.rag.context_builder import DEFAULT_TOP_N, build_context
from integration.rag.pipeline import UnstructuredSearcher
from integration.rag.rag_config import B2_DB_BLOCKS, B2_DOC_BLOCKS, RagConfig
from integration.rag.semantic_layer import SemanticLayer


def _fused(n_struct=7, n_doc=7):
    """RRF-style interleaving of two sources, best first."""
    s = [{"source": "structured", "dataset": "invoices", "record_id": f"S{i}", "content": f"row {i} xxxxx", "metadata": {}} for i in range(n_struct)]
    d = [{"source": "unstructured", "dataset": "novatel_synthetic", "record_id": f"D{i}", "content": f"doc {i} xxxxx", "metadata": {}} for i in range(n_doc)]
    return [x for pair in itertools.zip_longest(s, d) for x in pair if x is not None]


def _count(ctx):
    out = {"structured": 0, "unstructured": 0}
    for e in ctx["evidence"]:
        out[e["source"]] += 1
    return out


# ---- (ii) budget -------------------------------------------------------------------------------
def test_default_is_the_shared_six_block_budget():
    ctx = build_context(_fused(), top_n=DEFAULT_TOP_N, per_source_budget=RagConfig().per_source_budget)
    assert len(ctx["evidence"]) == DEFAULT_TOP_N == 6
    assert ctx["context_text"] == build_context(_fused(), top_n=DEFAULT_TOP_N)["context_text"]


def test_b2_budget_gives_configured_blocks_per_source():
    cfg = RagConfig.b2()
    assert (cfg.budget_db_blocks, cfg.budget_doc_blocks) == (B2_DB_BLOCKS, B2_DOC_BLOCKS) == (5, 3)
    assert _count(build_context(_fused(), per_source_budget=cfg.per_source_budget)) == {"structured": 5, "unstructured": 3}


def test_budget_is_capped_by_what_exists_and_order_is_preserved():
    ctx = build_context(_fused(n_struct=2, n_doc=7), per_source_budget=RagConfig(budget_db_blocks=5, budget_doc_blocks=3).per_source_budget)
    assert _count(ctx) == {"structured": 2, "unstructured": 3}
    assert [e["record_id"] for e in ctx["evidence"] if e["source"] == "unstructured"] == ["D0", "D1", "D2"]


@pytest.mark.parametrize("kwargs", [{"budget_db_blocks": 5}, {"budget_doc_blocks": 3}, {"budget_db_blocks": -1, "budget_doc_blocks": 3},
                                    {"semantic_max_chunks_per_doc": 0}])
def test_invalid_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        RagConfig(**kwargs)


# ---- (iii) semantic layer ------------------------------------------------------------------------
def _layer(related_edges=(), weight=0.5, expand_docs=("DOC_N",)):
    parts = {"classify": lambda q: {"concept_hint": "Recharge" if "recharge" in q.lower() else None},
             "graph_weight": lambda c: weight if c.get("concept_hint") else 0.0,
             "crosswalk_rows": [{"shared_domain_concept": "Recharge", "document_category_name": "Recharge & Payments"}],
             "graph_expand": lambda seeds, idx, bridges=None, limit=20: [{"document_id": d} for d in expand_docs],
             "graph_index": object(), "bridges": ("Service",), "seeds": 2, "candidates": 20,
             "related_edges": list(related_edges)}
    return SemanticLayer(_parts=parts)


class _FakeReranker:
    def predict(self, pairs):
        return [0.5 for _ in pairs]


def _searcher():
    s = object.__new__(UnstructuredSearcher)
    s.metadata = [{"document_id": "DOC_A", "chunk_id": "DOC_A_0"}, {"document_id": "DOC_B", "chunk_id": "DOC_B_0"},
                  {"document_id": "DOC_N", "chunk_id": "DOC_N_0"}, {"document_id": "DOC_N", "chunk_id": "DOC_N_1"},
                  {"document_id": "DOC_N", "chunk_id": "DOC_N_2"}]
    s.reranker = _FakeReranker()
    s._text_cache = {}
    s._load_text = lambda record: f"text of {record['chunk_id']}"
    s._dataset_label = staticmethod(lambda record: "novatel_synthetic")
    return s


def _cands():
    return [{"document_id": "DOC_A", "chunk_id": "DOC_A_0", "text": "a", "hybrid_score": 3.0, "faiss_score": .5, "_dataset": "novatel_synthetic"},
            {"document_id": "DOC_B", "chunk_id": "DOC_B_0", "text": "b", "hybrid_score": 2.0, "faiss_score": .4, "_dataset": "novatel_synthetic"}]


def test_layer_on_expands_the_pool_and_off_does_not():
    s, layer = _searcher(), _layer()
    expanded = s._semantic_merge("why did my recharge fail", _cands(), layer, layer.analyse("why did my recharge fail"))
    ids = [c["chunk_id"] for c in expanded]
    assert any(i.startswith("DOC_N") for i in ids) and len([i for i in ids if i.startswith("DOC_N")]) <= layer.max_chunks_per_doc
    # graph weight 0.0 (no concept) -> the graph must not touch the question
    not_touched = s._semantic_merge("hello there", _cands(), layer, layer.analyse("hello there"))
    assert [c["chunk_id"] for c in not_touched] == ["DOC_A_0", "DOC_B_0"]


def test_normalised_query_adds_ontology_terms_only_when_a_concept_matches():
    layer = _layer()
    text, info = layer.normalise_query("why did my recharge fail")
    assert text.startswith("why did my recharge fail") and "Recharge & Payments" in text and info["graph_weight"] == 0.5
    assert layer.normalise_query("hello there")[0] == "hello there"


def test_dangling_related_links_are_skipped_counted_and_logged_never_raised(caplog):
    layer = _layer(related_edges=[("DOC_A", "MISSING_1"), ("MISSING_2", "DOC_B"), ("DOC_A", "DOC_N")], expand_docs=())
    known = {"DOC_A", "DOC_B", "DOC_N"}
    with caplog.at_level(logging.WARNING, logger="novatel.semantic_layer"):
        got = layer.neighbours(["DOC_A", "DOC_B"], known)
        layer.neighbours(["DOC_A"], known)  # second call must not log again
    assert got == ["DOC_N"]                        # only the resolvable link contributes
    assert layer.stats["related_links_total"] == 3 and layer.stats["related_links_dangling"] == 2
    assert len([r for r in caplog.records if "dangling" in r.getMessage()]) == 1
    assert "2 of 3" in caplog.records[0].getMessage()


def test_all_links_dangling_is_harmless():
    layer = _layer(related_edges=[("X", "Y")], expand_docs=())
    assert layer.neighbours(["DOC_A"], {"DOC_A"}) == []
    assert layer.link_report({"DOC_A"}) == {"total": 1, "resolvable": 0, "dangling": 1}


def test_related_links_can_be_switched_off():
    layer = _layer(related_edges=[("DOC_A", "DOC_N")], expand_docs=())
    layer.use_related_links = False
    assert layer.neighbours(["DOC_A"], {"DOC_A", "DOC_N"}) == []
