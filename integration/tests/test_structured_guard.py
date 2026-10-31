"""Customer-scoped lookups on tables without customer_id: msisdn mapping, 'not executable' status, and what the answer says.

Real DB tests use the tracked SQLite file read-only and are skipped if it is absent; the rest use fakes.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

from integration.qa import system
from integration.qa.config import QAConfig
from integration.structured_guard import guarded_structured_search
from query_router.base import RouteDecision

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "processed" / "structured" / "novatel_structured.db"
needs_db = pytest.mark.skipif(not DB.exists(), reason="local SQLite DB not available")


@pytest.fixture(scope="module")
def retriever():
    if not DB.exists():
        pytest.skip("local SQLite DB not available")
    sys.path.insert(0, str(ROOT / "structured"))
    from retriever import StructuredRetriever
    r = StructuredRetriever()
    yield r
    r.close()


def _db_scalar(sql):
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


# ---- real DB ---------------------------------------------------------------------------------------------------------
@needs_db
def test_msisdn_keyed_table_is_answered_through_the_customers_msisdn(retriever):
    g = guarded_structured_search(retriever, "Show recharge transactions for customer 1056", 10)
    expected = _db_scalar("SELECT COUNT(*) FROM recharge_transactions WHERE msisdn = (SELECT msisdn FROM customer_master WHERE customer_id = 1056)")
    msisdn = _db_scalar("SELECT msisdn FROM customer_master WHERE customer_id = 1056")
    assert g.status["executed"] and g.status["route"] == "msisdn_mapping" and expected > 0
    assert len(g.results) == min(expected, 10) and all(str(r["metadata"]["msisdn"]) == msisdn for r in g.results)
    assert g.parsed["filter_column"] == "msisdn" and g.status["msisdn_lookup"]["filter_value"] == msisdn


@needs_db
def test_the_observed_failing_benchmark_question_now_runs(retriever):
    q = "For customer 1056: My last recharge didn't go through - what happens to the money, and what should I do?"
    g = guarded_structured_search(retriever, q, 10)
    assert g.status["executed"] and g.results


@needs_db
@pytest.mark.parametrize("q,table", [("Show network sites for customer 1056", "network_sites"), ("Show offers for customer 1056", "offers")])
def test_table_with_no_customer_or_msisdn_column_is_reported_not_executable(retriever, q, table):
    g = guarded_structured_search(retriever, q, 10)
    assert g.results == [] and g.status["executed"] is False and g.status["route"] == "not_executable"
    assert table in g.status["reason"] and "no customer_id and no msisdn" in g.status["reason"]


@needs_db
def test_unknown_customer_on_an_msisdn_table_is_reported_with_the_reason(retriever):
    g = guarded_structured_search(retriever, "Show recharge transactions for customer 99999", 10)
    assert g.status["executed"] is False and "customer_master has no row" in g.status["reason"]


@needs_db
def test_queries_that_worked_before_are_untouched(retriever):
    q = "Show invoices for customer 1829"
    direct = retriever.search(q, top_k=5)["results"]
    g = guarded_structured_search(retriever, q, 5)
    assert g.status["route"] == "direct" and [r["record_id"] for r in g.results] == [r["record_id"] for r in direct]


@needs_db
def test_e14_adapter_uses_the_guard_and_exposes_the_status():
    from integration.rag.pipeline import StructuredSearchAdapter
    a = StructuredSearchAdapter()
    try:
        assert a.search("Show recharge transactions for customer 1056")
        assert a.last_status["route"] == "msisdn_mapping"
        assert a.search("Show offers for customer 1056") == [] and a.last_status["executed"] is False
    finally:
        a.close()


# ---- fakes: error handling and ambiguous mapping ------------------------------------------------------------------------
class _Conn:
    def __init__(self, cols):
        self.cols = cols

    def execute(self, sql):
        if "sqlite_master" in sql:
            return [(t,) for t in self.cols]
        table = sql.split("(")[1].rstrip(")")
        return [(0, c, "TEXT") for c in self.cols[table]]


class _Loader:
    def __init__(self, cols):
        self.conn = _Conn(cols)


class _Retriever:
    def __init__(self, error, msisdn_rows, cols):
        self.error, self.msisdn_rows, self.loader = error, msisdn_rows, _Loader(cols)

    def search(self, q, top_k):
        raise self.error

    def exact_filter(self, table, column, value, top_k=10):
        if table == "customer_master":
            return {"results": [{"metadata": {"msisdn": m}} for m in self.msisdn_rows]}
        return {"results": [{"record_id": "1", "metadata": {"msisdn": value}}]}


def test_other_errors_are_not_swallowed():
    r = _Retriever(ValueError("boom"), ["9"], {"recharge_transactions": ["msisdn"]})
    with pytest.raises(ValueError):
        guarded_structured_search(r, "Show recharge transactions for customer 1056", 5)
    r = _Retriever(sqlite3.OperationalError("no such table: nope"), ["9"], {})
    with pytest.raises(sqlite3.OperationalError):
        guarded_structured_search(r, "Show recharge transactions for customer 1056", 5)


def test_a_customer_with_two_msisdns_is_not_guessed():
    err = sqlite3.OperationalError("no such column: customer_id")
    g = guarded_structured_search(_Retriever(err, ["111", "222"], {"recharge_transactions": ["msisdn"]}),
                                  "Show recharge transactions for customer 1056", 5)
    assert g.status["executed"] is False and "more than one msisdn" in g.status["reason"]


# ---- what the answer says --------------------------------------------------------------------------------------------------
UNEXEC = {"executed": False, "unexecutable_reason": "table 'offers' has no customer_id and no msisdn column", "lookup_route": "not_executable",
          "msisdn_lookup": None, "sub_query": "q", "n_results": 0}


class _FakeStructured:
    def can_execute(self, q):
        return True, {"table": "offers"}

    def search(self, q, cfg, origin="original"):
        return [], dict(UNEXEC)


class _FakeUnstructured:
    def __init__(self, ev):
        self.ev = ev

    def search(self, q, cfg, origin="original"):
        return self.ev, {"top_crossencoder_sigmoid": 0.95, "components": []}


class _FakeDecomposer:
    def decompose(self, q):
        return {"structured": "Show offers for customer 1056", "unstructured": "What offers exist?", "structured_parse_ok": True,
                "structured_parsed": {}, "structured_method": "llm", "unstructured_from_llm": True, "notes": []}

    def rewrite_for_parser(self, q):
        return {"structured": None, "parsed": None, "method": "none", "notes": []}


def _doc():
    from integration.qa.evidence import unstructured_evidence
    return unstructured_evidence(document_id="DOC-1", chunk_id="DOC-1_c0", dataset="novatel_synthetic", category="x",
                                 content="Offers can be combined only when an offer says it is stackable.", title="Offers",
                                 retrieval_method="m", raw_scores={}, score=1.0, sub_query="q", origin="original")


def _wire(monkeypatch, label, answer="Offers can be combined only when an offer says it is stackable. [E1]"):
    monkeypatch.setattr(system, "_route", lambda q, cfg: (RouteDecision.from_label(label, router_name="fake", model_id="fake"), {}))
    monkeypatch.setattr(system, "_STRUCTURED", _FakeStructured())
    monkeypatch.setattr(system, "get_unstructured", lambda: _FakeUnstructured([_doc()]))
    monkeypatch.setattr(system, "get_decomposer", lambda m: _FakeDecomposer())
    monkeypatch.setattr(system, "generate", lambda q, ev, cfg, sq=None: answer)


CFG = QAConfig(verifier="lexical", router_conf_threshold=0.0, retrieval_conf_threshold=0.5)


def test_structured_route_says_the_lookup_could_not_be_run(monkeypatch):
    _wire(monkeypatch, "structured")
    r = system.answer_query("Show offers for customer 1056", CFG)
    assert r["abstained"] is False and r["abstention"]["layer"] is None
    assert "could not be executed" in r["answer_text"] and "offers" in r["answer_text"]
    assert r["answer_text"] != CFG.abstention_message and r["structured_status"]["executed"] is False
    assert r["route"]["final_route"] == "structured"          # no silent fall-back to documents for a data question


def test_hybrid_route_answers_the_document_half_and_names_the_missing_half(monkeypatch):
    _wire(monkeypatch, "hybrid")
    r = system.answer_query("What offers does customer 1056 have and can two offers be combined?", CFG)
    assert not r["abstained"] and "NOT ANSWERED" in r["answer_text"] and "could not be executed" in r["answer_text"]
    d = r["hybrid_diagnostics"]
    assert d["structured_half_executed"] is False and "offers" in d["structured_unexecutable_reason"] and d["half_answered"]
    assert all(e["source"] != "structured" for e in r["evidence"])


def test_executed_lookup_with_no_rows_is_still_a_genuine_no_evidence_case(monkeypatch):
    class Empty(_FakeStructured):
        def search(self, q, cfg, origin="original"):
            return [], {"executed": True, "unexecutable_reason": None, "lookup_route": "direct", "msisdn_lookup": None,
                        "sub_query": q, "n_results": 0}
    _wire(monkeypatch, "structured", answer="x")
    monkeypatch.setattr(system, "_STRUCTURED", Empty())
    monkeypatch.setattr(system, "get_unstructured", lambda: _FakeUnstructured([]))
    r = system.answer_query("Show tickets for customer 1", CFG)
    assert r["abstained"] and r["abstention"]["layer"] == 2 and r["structured_status"]["executed"] is True
