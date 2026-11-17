"""Customer-scoped lookups: the guard READS Person B's contract (structured/retriever.py::customer_scoped_filter, 7adfb65) and
reports it. Agreed contract:
  * executed is a bool; False ONLY when the table cannot be scoped (empty_reason table_not_scopable / unknown_table);
  * route "msisdn_mapping" only on the msisdn path; otherwise "direct" when executed, None when not;
  * empty_reason: None when rows came back; no_rows (customer_id table, or a mapped msisdn with no rows); unknown_customer
    (msisdn path only, also a customer with more than one customer_master row); table_not_scopable; unknown_table;
  * unknown customer / no rows are "nothing found" (executed True), never "could not be executed";
  * user-facing wording is ours (status["reason"], only when executed is False), never the retriever's note text.

Real DB tests use the tracked SQLite file read-only (a temp COPY for the two-msisdn case) and are skipped if it is absent; the rest use fakes.
"""

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from integration.qa import system
from integration.qa.config import QAConfig
from integration.structured_guard import guarded_structured_search, status_from_result
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
    assert g.status["executed"] is True and g.status["route"] == "msisdn_mapping" and g.status["empty_reason"] is None and expected > 0
    assert len(g.results) == min(expected, 10) and all(str(r["metadata"]["msisdn"]) == msisdn for r in g.results)
    assert g.parsed["filter_column"] == "msisdn" and g.status["msisdn_lookup"]["filter_value"] == msisdn
    assert g.status["customer_id"] == "1056" and g.status["table"] == "recharge_transactions" and g.status["reason"] is None


@needs_db
def test_the_observed_failing_benchmark_question_now_runs(retriever):
    q = "For customer 1056: My last recharge didn't go through - what happens to the money, and what should I do?"
    g = guarded_structured_search(retriever, q, 10)
    assert g.status["executed"] is True and g.results and g.status["route"] == "msisdn_mapping"


@needs_db
@pytest.mark.parametrize("q,table", [("Show network sites for customer 1056", "network_sites"), ("Show offers for customer 1056", "offers")])
def test_table_with_no_customer_or_msisdn_column_is_reported_not_executable(retriever, q, table):
    g = guarded_structured_search(retriever, q, 10)
    assert g.results == [] and g.status["executed"] is False and g.status["empty_reason"] == "table_not_scopable" and g.status["route"] is None
    assert table in g.status["reason"] and "no customer_id and no msisdn" in g.status["reason"]
    assert "table has no customer key" not in g.status["reason"]           # our wording, not the retriever's developer note


@needs_db
def test_unknown_customer_on_an_msisdn_table_is_nothing_found_not_unexecuted(retriever):
    g = guarded_structured_search(retriever, "Show recharge transactions for customer 99999", 10)
    assert g.results == [] and g.status["executed"] is True and g.status["empty_reason"] == "unknown_customer"
    assert g.status["route"] == "direct" and g.status["reason"] is None and g.status["msisdn_lookup"] is None   # the retriever sets no route on this path


@needs_db
def test_unknown_customer_on_a_customer_id_table_is_no_rows(retriever):
    g = guarded_structured_search(retriever, "Show invoices for customer 99999", 10)
    assert g.results == [] and g.status["executed"] is True and g.status["empty_reason"] == "no_rows"
    assert g.status["route"] == "direct" and g.status["reason"] is None


@needs_db
def test_direct_table_with_rows_has_no_empty_reason_and_the_retrievers_own_rows(retriever):
    q = "Show invoices for customer 1829"
    direct = retriever.search(q, top_k=5)["results"]
    g = guarded_structured_search(retriever, q, 5)
    assert direct and g.status["route"] == "direct" and g.status["executed"] is True and g.status["empty_reason"] is None
    assert [r["record_id"] for r in g.results] == [r["record_id"] for r in direct]
    assert g.parsed["filter_column"] == "customer_id"                       # not rewritten: no msisdn mapping happened


@needs_db
def test_unresolved_question_ran_normally_and_found_nothing(retriever):
    g = guarded_structured_search(retriever, "Why is my latest postpaid bill higher than the monthly rental I expected to pay?", 5)
    assert g.results == [] and g.status["executed"] is True and g.status["route"] == "direct" and g.status["empty_reason"] is None
    assert g.parsed["method"] == "exact_filter_unresolved" and g.status["note"]


@needs_db
def test_e14_adapter_uses_the_guard_and_exposes_the_status():
    from integration.rag.pipeline import StructuredSearchAdapter
    a = StructuredSearchAdapter()
    try:
        assert a.search("Show recharge transactions for customer 1056")
        assert a.last_status["route"] == "msisdn_mapping" and a.last_status["executed"] is True and a.last_status["empty_reason"] is None
        assert a.search("Show offers for customer 1056") == []
        assert a.last_status["executed"] is False and a.last_status["route"] is None and a.last_status["empty_reason"] == "table_not_scopable"
        assert a.search("Show recharge transactions for customer 99999") == []
        assert a.last_status["executed"] is True and a.last_status["empty_reason"] == "unknown_customer"
    finally:
        a.close()


@needs_db
def test_a_customer_with_two_msisdns_is_not_guessed(tmp_path):
    """Real SQLite COPY with a second customer_master row for customer 1056: no msisdn is picked, no rows are returned."""
    db = tmp_path / "two_msisdns.db"
    shutil.copy(DB, db)
    con = sqlite3.connect(db)
    con.execute("INSERT INTO customer_master SELECT customer_id, '0000000000', name, dob, email, address, circle, account_type, "
                "activation_date, kyc_status, status FROM customer_master WHERE customer_id = '1056'")
    con.commit()
    con.close()
    sys.path.insert(0, str(ROOT / "structured"))
    from retriever import StructuredRetriever
    r = StructuredRetriever(db_path=str(db))
    try:
        g = guarded_structured_search(r, "Show recharge transactions for customer 1056", 10)
    finally:
        r.close()
    assert g.results == [] and g.status["executed"] is True and g.status["empty_reason"] == "unknown_customer"
    assert g.status["route"] != "msisdn_mapping" and g.status["msisdn_lookup"] is None and g.parsed["filter_column"] == "customer_id"


# ---- fakes: the status mapping and error handling -------------------------------------------------------------------------
class _Fake:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def search(self, q, top_k):
        if self.error:
            raise self.error
        return self.result


PARSED = {"table": "recharge_transactions", "method": "exact_filter", "filter_column": "customer_id", "filter_value": 1056}


def test_status_mapping_follows_the_contract_for_every_empty_reason():
    cases = [  # (result keys, executed, route, empty_reason)
        ({"results": [], "executed": False, "empty_reason": "table_not_scopable", "note": "dev"}, False, None, "table_not_scopable"),
        ({"results": [], "executed": False, "empty_reason": "unknown_table", "note": "dev"}, False, None, "unknown_table"),
        ({"results": [], "executed": True, "empty_reason": "unknown_customer", "note": "dev"}, True, "direct", "unknown_customer"),
        ({"results": [], "executed": True, "empty_reason": "no_rows"}, True, "direct", "no_rows"),
        ({"results": [], "executed": True, "route": "msisdn_mapping", "empty_reason": "no_rows"}, True, "msisdn_mapping", "no_rows"),
        ({"results": [{"record_id": "1", "metadata": {"msisdn": "9"}}], "executed": True, "route": "msisdn_mapping", "empty_reason": None},
         True, "msisdn_mapping", None),
        ({"results": [{"record_id": "1", "metadata": {}}], "executed": True, "empty_reason": None}, True, "direct", None),
    ]
    for res, executed, route, reason in cases:
        g = guarded_structured_search(_Fake({**res, "parsed_query": dict(PARSED)}), "q", 5)
        assert (g.status["executed"], g.status["route"], g.status["empty_reason"]) == (executed, route, reason), res
        assert (g.status["reason"] is None) == executed                       # our wording only when it could not be executed
        if not executed:
            assert "dev" not in g.status["reason"]                             # the retriever's note is never reused as user wording


def test_result_without_an_executed_key_ran_normally():
    status, _ = status_from_result({"results": [], "parsed_query": {"table": None}, "note": "Query could not be confidently resolved"})
    assert status["executed"] is True and status["route"] == "direct" and status["empty_reason"] is None


def test_non_bool_executed_is_a_contract_violation():
    with pytest.raises(TypeError):
        guarded_structured_search(_Fake({"results": [], "executed": "yes", "parsed_query": dict(PARSED)}), "q", 5)


def test_other_errors_are_not_swallowed():
    for err in (ValueError("boom"), sqlite3.OperationalError("no such table: nope"),
                sqlite3.OperationalError("no such column: customer_id")):    # the old guard caught this one; now it is a real error
        with pytest.raises(type(err)):
            guarded_structured_search(_Fake(error=err), "Show recharge transactions for customer 1056", 5)


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
