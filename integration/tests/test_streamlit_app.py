"""UI smoke tests with Streamlit's AppTest. The pipeline and router probing are replaced by fakes so no model loads."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import integration.qa.system as system  # noqa: E402
import query_router.registry as registry  # noqa: E402

APP = str(Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py")

EVIDENCE_DB = {"evidence_id": "E1", "source": "structured", "dataset": "invoices", "retrieval_method": "exact_filter",
               "score": 1.0, "raw_scores": {}, "origin_subquery": "structured_subquery", "text": "invoice INV-1 <b>Overdue</b>",
               "kind": "table_row", "table": "invoices", "row_id": "INV-1", "columns_used": ["status"],
               "query_or_lookup": "SELECT * FROM invoices WHERE customer_id = '1025'", "label": "table invoices, row INV-1",
               "cited": True, "cited_by_sentence": [0], "supporting_spans": []}
EVIDENCE_DOC = {"evidence_id": "E2", "source": "unstructured", "dataset": "novatel_synthetic", "retrieval_method": "faiss",
                "score": 3.0, "raw_scores": {}, "origin_subquery": "unstructured_subquery", "text": "A late fee of 2 percent applies.",
                "kind": "document_chunk", "corpus": "NovaTel Synthetic", "document_id": "DOC-1", "chunk_id": "DOC-1_c0",
                "page_number": None, "label": "NovaTel Synthetic: DOC-1 / DOC-1_c0", "cited": True,
                "cited_by_sentence": [1], "supporting_spans": ["A late fee of 2 percent applies."]}


def _base(**kw):
    r = {"query": "q", "answer_text": "", "sentences": [], "evidence": [], "route": {"label": "hybrid", "final_route": "hybrid",
         "confidence": 0.91}, "router_name": "laya_finetuned", "abstained": False, "abstention": {"layer": None, "reason": None},
         "hybrid_diagnostics": None, "fallback": {"occurred": False}, "timings": {"total_ms": 12.0}, "config": {}, "error": None}
    r.update(kw)
    return r


HYBRID = _base(
    answer_text="x",
    sentences=[{"text": "Invoice INV-1 is Overdue.", "citations": ["E1"], "support_status": "SUPPORTED", "support": {}},
               {"text": "A late fee of 2 percent applies.", "citations": ["E2"], "support_status": "WEAK", "support": {}}],
    evidence=[EVIDENCE_DB, EVIDENCE_DOC], unanswered=["the refund deadline"],
    hybrid_diagnostics={"structured_sub_query": "Show invoices for customer 1025", "unstructured_sub_query": "late fee rules",
                        "structured_half_found": True, "unstructured_half_found": True, "decomposer_method": "llm",
                        "sources_cited_in_answer": ["structured", "unstructured"], "half_answered": True})
ABSTAIN = _base(abstained=True, answer_text="I don't have information about that in the NovaTel knowledge base.",
                route={"label": "out_of_scope", "final_route": "out_of_scope", "confidence": 0.99},
                abstention={"layer": 1, "reason": "the router judged this question out of scope"})


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(registry, "router_status", lambda name, cfg=None: (name != "laya_zeroshot", "weights missing"))
    monkeypatch.setattr(system, "get_unstructured", lambda: object())
    return lambda: AppTest.from_file(APP, default_timeout=30)


def _run(app, result, query="Customer 1025 overdue invoice and fee?"):
    monkey = system
    monkey.answer_query = lambda q, cfg=None: result
    at = app()
    at.run()
    assert not at.exception
    at.text_area[0].set_value(query)
    at.button[0].click()
    at.run()
    assert not at.exception, at.exception
    return at


def test_hybrid_render(app):
    saved = system.answer_query
    try:
        at = _run(app, HYBRID)
        html = " ".join(m.value for m in at.markdown)
        assert "ROUTE: HYBRID" in html and "ROUTER: laya_finetuned" in html
        assert "DATABASE SUB-QUERY" in html and "PARTLY ANSWERED" in html and "the refund deadline" in html
        assert "<b>Overdue</b>" not in html  # evidence text from the DB is escaped, never injected as markup
        assert "&lt;b&gt;Overdue&lt;/b&gt;" in html
    finally:
        system.answer_query = saved


def test_abstention_card_and_no_citations(app):
    saved = system.answer_query
    try:
        at = _run(app, ABSTAIN, "What is the weather?")
        html = " ".join(m.value for m in at.markdown)
        assert "I DON'T KNOW THAT ONE" in html and 'class="cite"' not in html
    finally:
        system.answer_query = saved


def test_pipeline_exception_is_shown_not_raised(app):
    saved = system.answer_query

    def boom(q, cfg=None):
        raise RuntimeError("backend down")

    try:
        system.answer_query = boom
        at = app()
        at.run()
        at.text_area[0].set_value("anything")
        at.button[0].click()
        at.run()
        assert not at.exception
        assert "GAME OVER" in " ".join(m.value for m in at.markdown) and "backend down" in " ".join(m.value for m in at.markdown)
    finally:
        system.answer_query = saved


def test_unavailable_router_is_not_selectable(app):
    at = app()
    at.run()
    options = at.sidebar.selectbox[0].options
    assert "laya_zeroshot" not in options and "auto" in options
