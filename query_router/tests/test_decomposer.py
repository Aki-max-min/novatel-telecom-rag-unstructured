"""Regression: a non-string value in the decomposer LLM's JSON must never reach structured/query_parser.py
(it used to raise AttributeError: 'list' object has no attribute 'lower'). The LLM is stubbed; the real rule-based parser is used."""

import pytest

from query_router.decomposer import HybridDecomposer, coerce_query

QUESTION = "What is the KYC status of customer 1042, and how much does the NovaTel satellite phone plan cost?"


@pytest.fixture
def dec(monkeypatch):
    d = HybridDecomposer("none")

    def stub(payload):
        monkeypatch.setattr(d, "_call_llm", lambda q, notes: payload)
        return d
    d.stub = stub
    return d


# ---- coerce_query ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [
    ("Show invoices for customer 1025", "Show invoices for customer 1025"),
    ("  padded  ", "padded"),
    (["Show kyc records for customer 1042"], "Show kyc records for customer 1042"),
    (["", "  ", "Show tickets for customer 7"], "Show tickets for customer 7"),
    (["first lookup", "second lookup"], "first lookup"),
])
def test_coerce_returns_a_string(value, expected):
    assert coerce_query(value)[0] == expected


@pytest.mark.parametrize("value", [None, "", "   ", [], [None, 3], {"q": "x"}, 42, 3.5, True])
def test_coerce_rejects_everything_else(value):
    assert coerce_query(value)[0] is None


def test_coerce_records_a_note_when_it_changes_the_value():
    assert "one-element list" in coerce_query(["x y"])[1]
    assert "first of 2" in coerce_query(["a", "b"])[1]
    assert coerce_query("plain")[1] is None


# ---- _executable never raises -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [["Show invoices for customer 1025"], [], None, {"x": 1}, 7, [None]])
def test_executable_does_not_raise_on_non_strings(dec, bad):
    ok, parsed = dec._executable(bad, ["invoices"])   # structured_table may be a list too
    assert isinstance(ok, bool) and isinstance(parsed, dict)


def test_list_with_an_executable_lookup_is_coerced_and_executable(dec):
    ok, parsed = dec._executable(["Show invoices for customer 1025"], "invoices")
    assert ok and parsed["table"] == "invoices"


def test_unusable_values_are_rejected_not_parsed(dec):
    ok, parsed = dec._executable({"q": "x"})
    assert ok is False and parsed["table"] is None


# ---- the two public paths ---------------------------------------------------------------------------------------------
def test_decompose_survives_a_list_typed_structured_answer(dec):
    dec.stub({"structured": ["Show invoices for customer 1025"], "structured_table": ["invoices"],
              "unstructured": "What are the late payment rules?"})
    out = dec.decompose("Customer 1025 has an overdue invoice. What late-payment rules apply?")
    assert out["structured"] == "Show invoices for customer 1025" and out["structured_method"] == "llm"
    assert out["structured_parse_ok"] and any("one-element list" in n for n in out["notes"])


def test_decompose_falls_back_to_templates_when_the_list_is_unusable(dec):
    dec.stub({"structured": [], "structured_table": None, "unstructured": ["not a string either"]})
    out = dec.decompose("Customer 1025 has an overdue invoice. What late-payment rules apply?")
    assert out["structured_method"] == "rule_template" and "1025" in out["structured"]
    assert out["unstructured_from_llm"] is False


def test_rewrite_for_parser_survives_a_list(dec):
    dec.stub({"structured": ["What is the account status of customer 1042?"], "structured_table": "customer_master"})
    out = dec.rewrite_for_parser(QUESTION)
    assert out["structured"] == "What is the account status of customer 1042?" and out["method"] == "llm"


def test_the_observed_failing_input_no_longer_crashes(dec):
    """Observed in a demo run: a two-part question whose structured part the LLM returned as a list."""
    dec.stub({"structured": ["Show kyc records for customer 1042"], "structured_table": "kyc_records",
              "unstructured": "How much does the NovaTel satellite phone plan cost?"})
    out = dec.decompose(QUESTION)
    assert out["structured"] and out["unstructured"].startswith("How much")
