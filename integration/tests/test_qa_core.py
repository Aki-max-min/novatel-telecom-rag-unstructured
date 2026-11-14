"""Evidence schema, sentence/citation parser, verifier, abstention gate, decomposer, and answer_query routing.

No model weights, Ollama server, FAISS index or SQLite DB are touched: backends, router and generator are
replaced by deterministic fakes, and the verifier runs in its lexical mode.
"""

import pytest

from integration.qa import abstain, citations as cit, system
from integration.qa.config import QAConfig
from integration.qa.evidence import (CORE_KEYS, assign_evidence_ids, structured_evidence, unstructured_evidence,
                                     validate_core)
from query_router.base import RouteDecision
from query_router.decomposer import HybridDecomposer


# ---- fixtures ------------------------------------------------------------------
def _sev(row_id="INV-1", content="invoice INV-1 for customer 1025 has amount 1500 and status Overdue", **md):
    return structured_evidence(
        {"record_id": row_id, "dataset": "invoices", "score": 1.0, "retrieval_method": "exact_filter",
         "content": content, "metadata": {"customer_id": 1025, "amount": 1500, "status": "Overdue", **md}},
        parsed={"table": "invoices", "method": "exact_filter", "filter_column": "customer_id", "filter_value": 1025},
        sub_query="Show invoices for customer 1025", origin="original", primary_key="invoice_id")


def _uev(chunk="DOC-1_c0", content="A late payment fee of 2 percent applies after the due date. Service may be suspended.",
         sigmoid=0.9):
    return unstructured_evidence(
        document_id="DOC-1", chunk_id=chunk, dataset="novatel_synthetic", category="billing", content=content,
        title="Billing policy", retrieval_method="faiss+crossencoder",
        raw_scores={"crossencoder_sigmoid": sigmoid}, score=3.0, sub_query="late payment rules", origin="original")


LEX = QAConfig(verifier="lexical", router_conf_threshold=0.0, retrieval_conf_threshold=0.5)


# ---- evidence interface -----------------------------------------------------------
def test_core_keys_identical_for_both_sources():
    for ev in (_sev(), _uev()):
        assert set(ev) == set(CORE_KEYS)
        validate_core(ev)


def test_extended_metadata_present_and_not_invented():
    s, u = _sev(), _uev()
    assert s["metadata"]["table_name"] == "invoices" and s["metadata"]["chunk_id"] is None
    assert u["metadata"]["chunk_id"] == "DOC-1_c0" and u["metadata"]["table_name"] is None
    assert "WHERE customer_id = '1025'" in s["metadata"]["query_or_lookup"]


def test_evidence_ids_are_stable_sequential():
    ids = [e["metadata"]["evidence_id"] for e in assign_evidence_ids([_sev("A"), _uev(), _sev("B")])]
    assert ids == ["E1", "E2", "E3"]


# ---- parser -------------------------------------------------------------------------
def test_parser_splits_sentences_and_tags():
    raw = "Your invoice is overdue. [E1] A 2 percent late fee applies [E2][E3]."
    p = cit.parse_answer(raw, {"E1", "E2", "E3"})
    assert [s["citations"] for s in p["sentences"]] == [["E1"], ["E2", "E3"]]


def test_parser_never_accepts_unsupplied_ids():
    p = cit.parse_answer("The fee is 2 percent. [E9]", {"E1"})
    assert p["sentences"][0]["citations"] == [] and p["sentences"][0]["invalid_citations"] == ["E9"]


def test_parser_insufficient_and_not_answered():
    assert cit.parse_answer("INSUFFICIENT_EVIDENCE", {"E1"})["insufficient"] is True
    p = cit.parse_answer("The invoice is overdue. [E1]\nNOT ANSWERED: the refund deadline", {"E1"})
    assert p["unanswered"] == ["the refund deadline"] and len(p["sentences"]) == 1


def test_parser_tolerates_mistyped_not_answered_marker():
    p = cit.parse_answer("The invoice is overdue. [E1]\nNOT ANSWED: the refund deadline", {"E1"})
    assert p["unanswered"] == ["the refund deadline"] and len(p["sentences"]) == 1


def test_parser_handles_bullets_and_prose_drift():
    p = cit.parse_answer("- The invoice is overdue [E1]\n* The amount is 1500 [E1].", {"E1"})
    assert len(p["sentences"]) == 2 and all(s["citations"] == ["E1"] for s in p["sentences"])


# ---- verifier -----------------------------------------------------------------------
def _verify(sentence, cited, cfg=LEX):
    return cit.verify_sentence(sentence, cited, cfg)


def test_verifier_supports_faithful_sentence():
    v = _verify("A late payment fee of 2 percent applies after the due date.", [assign_evidence_ids([_uev()])[0]])
    assert v.status == cit.SUPPORTED and v.numbers_ok


def test_verifier_flags_wrong_number():
    v = _verify("A late payment fee of 7 percent applies after the due date.", [assign_evidence_ids([_uev()])[0]])
    assert v.status == cit.UNSUPPORTED and v.missing_numbers == ["7"]


def test_verifier_flags_missing_citation():
    assert _verify("The sky is blue.", []).status == cit.UNSUPPORTED


def test_verifier_does_not_support_off_topic_sentence():
    v = _verify("Roaming charges are waived for premium customers abroad.", [assign_evidence_ids([_uev()])[0]])
    assert v.status != cit.SUPPORTED


def test_verifier_handles_structured_numbers_with_commas():
    ev = assign_evidence_ids([_sev(content="invoice INV-1 amount 1500.00 status Overdue")])[0]
    assert _verify("The invoice amount is 1,500.", [ev]).numbers_ok


# ---- abstention gate -----------------------------------------------------------------
def test_gate_structured_needs_a_record():
    assert abstain.retrieval_gate("structured", [], [], None, LEX)["abstain"] is True
    assert abstain.retrieval_gate("structured", [_sev()], [], None, LEX)["abstain"] is False


def test_gate_unstructured_uses_threshold():
    weak = abstain.retrieval_gate("unstructured", [], [_uev()], {"top_crossencoder_sigmoid": 0.2}, LEX)
    strong = abstain.retrieval_gate("unstructured", [], [_uev()], {"top_crossencoder_sigmoid": 0.8}, LEX)
    assert weak["abstain"] and not strong["abstain"]


def test_gate_hybrid_abstains_only_if_both_halves_empty():
    one = abstain.retrieval_gate("hybrid", [_sev()], [_uev()], {"top_crossencoder_sigmoid": 0.1}, LEX)
    none = abstain.retrieval_gate("hybrid", [], [_uev()], {"top_crossencoder_sigmoid": 0.1}, LEX)
    assert not one["abstain"] and one["structured_usable"] and not one["unstructured_usable"]
    assert none["abstain"]


# ---- decomposer (LLM stubbed) ----------------------------------------------------------
def test_decomposer_rule_template_when_llm_down(monkeypatch):
    d = HybridDecomposer("none")
    monkeypatch.setattr(d, "_call_llm", lambda q, notes: None)
    out = d.decompose("Customer 1025 has an overdue invoice. What late-payment rules apply?")
    assert out["structured_method"] == "rule_template" and out["structured_parse_ok"]
    assert "1025" in out["structured"] and "1025" not in out["unstructured"]


def test_decomposer_rejects_unexecutable_llm_subquery(monkeypatch):
    d = HybridDecomposer("none")
    monkeypatch.setattr(d, "_call_llm", lambda q, notes: {
        "structured": "gibberish lookup xyz", "structured_table": "invoices",
        "unstructured": "What are the late payment rules?"})
    out = d.decompose("Customer 1025 has an overdue invoice. What late-payment rules apply?")
    assert out["structured_method"] == "rule_template"  # the LLM output was NOT trusted
    assert out["unstructured"] == "What are the late payment rules?"


# ---- answer_query end-to-end with fakes -------------------------------------------------
class _FakeStructured:
    def __init__(self, evidence):
        self.evidence = evidence

    def can_execute(self, q):
        return True, {"table": "invoices"}

    def search(self, q, cfg, origin="original"):
        return self.evidence, {"sub_query": q, "n_results": len(self.evidence), "resolved": True}


class _FakeUnstructured:
    def __init__(self, evidence, sigmoid):
        self.evidence, self.sigmoid = evidence, sigmoid

    def search(self, q, cfg, origin="original"):
        return self.evidence, {"sub_query": q, "n_results": len(self.evidence),
                               "top_crossencoder_sigmoid": self.sigmoid, "components": []}


class _FakeDecomposer:
    def decompose(self, q):
        return {"structured": "Show invoices for customer 1025", "unstructured": "What are the late payment rules?",
                "structured_parse_ok": True, "structured_parsed": {}, "structured_method": "llm",
                "unstructured_from_llm": True, "notes": []}

    def rewrite_for_parser(self, q):
        return {"structured": None, "parsed": None, "method": "none", "notes": []}


def _decision(label, confidence):
    d = RouteDecision.from_label(label, router_name="fake", model_id="fake")
    d.confidence = confidence
    return d


@pytest.fixture
def wire(monkeypatch):
    def _wire(label, *, s_ev=(), u_ev=(), u_sigmoid=0.9, answer="", confidence=0.95):
        monkeypatch.setattr(system, "_route", lambda q, cfg: (_decision(label, confidence), {}))
        monkeypatch.setattr(system, "_STRUCTURED", _FakeStructured(list(s_ev)))
        monkeypatch.setattr(system, "get_unstructured", lambda: _FakeUnstructured(list(u_ev), u_sigmoid))
        monkeypatch.setattr(system, "get_decomposer", lambda m: _FakeDecomposer())
        monkeypatch.setattr(system, "generate", lambda q, ev, cfg, sq=None: answer)
    return _wire


def test_structured_route_answers_with_row_citation(wire):
    wire("structured", s_ev=[_sev()], answer="Invoice INV-1 for customer 1025 is Overdue. [E1]")
    r = system.answer_query("Show invoices for customer 1025", LEX)
    assert not r["abstained"] and r["route"]["final_route"] == "structured"
    assert r["sentences"][0]["citations"] == ["E1"] and r["evidence"][0]["table"] == "invoices"
    assert set(r) >= {"answer_text", "sentences", "evidence", "route", "router_name", "abstained",
                      "hybrid_diagnostics", "timings"}


def test_unstructured_route_cites_chunk(wire):
    wire("unstructured", u_ev=[_uev()], answer="A late payment fee of 2 percent applies after the due date. [E1]")
    r = system.answer_query("What is the late payment fee?", LEX)
    assert r["sentences"][0]["support_status"] == cit.SUPPORTED and r["evidence"][0]["chunk_id"] == "DOC-1_c0"


def test_hybrid_route_cites_both_kinds_and_reports_diagnostics(wire):
    wire("hybrid", s_ev=[_sev()], u_ev=[_uev()],
         answer="Invoice INV-1 for customer 1025 is Overdue. [E1]\n"
                "A late payment fee of 2 percent applies after the due date. [E2]")
    r = system.answer_query("Customer 1025 has an overdue invoice - what late fee applies?", LEX)
    d = r["hybrid_diagnostics"]
    assert d["structured_sub_query"] and d["unstructured_sub_query"]
    assert set(d["sources_cited_in_answer"]) == {"structured", "unstructured"} and not d["half_answered"]


def test_half_answerable_states_gap_and_does_not_invent(wire):
    wire("hybrid", s_ev=[_sev()], u_ev=[_uev()], u_sigmoid=0.05,
         answer="Invoice INV-1 for customer 1025 is Overdue. [E1]\nNOT ANSWERED: the late payment fee rule")
    r = system.answer_query("Customer 1025 overdue invoice and fee rule?", LEX)
    assert not r["abstained"] and r["hybrid_diagnostics"]["half_answered"]
    assert "NOT ANSWERED" in r["answer_text"] and all(e["source"] == "structured" for e in r["evidence"])


def test_router_out_of_scope_abstains_without_retrieval(wire):
    wire("out_of_scope", answer="should never be used")
    r = system.answer_query("What is the weather in Paris?", LEX)
    assert r["abstained"] and r["abstention"]["layer"] == 1 and r["sentences"] == [] and r["evidence"] == []
    assert r["answer_text"] == LEX.abstention_message


def test_retrieval_gate_abstains_with_no_citations(wire):
    wire("unstructured", u_ev=[_uev()], u_sigmoid=0.01, answer="x")
    r = system.answer_query("Who is the CEO of a rival company?", LEX)
    assert r["abstained"] and r["abstention"]["layer"] == 2 and not r["evidence"] and "[E" not in r["answer_text"]


def test_generator_insufficient_evidence_abstains_layer3(wire):
    wire("unstructured", u_ev=[_uev()], answer="INSUFFICIENT_EVIDENCE")
    r = system.answer_query("something answerable-looking", LEX)
    assert r["abstained"] and r["abstention"]["layer"] == 3 and r["evidence"] == []


def test_low_router_confidence_becomes_hybrid(wire):
    wire("structured", s_ev=[_sev()], u_ev=[_uev()], confidence=0.55,
         answer="Invoice INV-1 for customer 1025 is Overdue. [E1]")
    cfg = QAConfig(verifier="lexical", router_conf_threshold=0.7, retrieval_conf_threshold=0.5)
    r = system.answer_query("ambiguous", cfg)
    assert r["route"]["label"] == "structured" and r["route"]["final_route"] == "hybrid"


def test_weak_single_route_retries_other_source_and_logs_it(wire):
    wire("structured", s_ev=[], u_ev=[_uev()],
         answer="A late payment fee of 2 percent applies after the due date. [E1]")
    r = system.answer_query("what late fee applies?", LEX)
    assert r["fallback"]["occurred"] and r["fallback"]["recovered"] and not r["abstained"]


def test_unsupported_sentence_is_flagged_or_dropped(wire):
    ans = "A late payment fee of 9 percent applies after the due date. [E1]"
    wire("unstructured", u_ev=[_uev()], answer=ans)
    kept = system.answer_query("fee?", LEX)
    assert kept["sentences"][0]["support_status"] == cit.UNSUPPORTED
    dropped = system.answer_query("fee?", QAConfig(verifier="lexical", router_conf_threshold=0.0,
                                                   retrieval_conf_threshold=0.5, drop_unsupported=True))
    assert dropped["abstained"] and dropped["abstention"]["layer"] == 3


def test_invalid_citation_never_resolves(wire):
    wire("unstructured", u_ev=[_uev()], answer="A late payment fee of 2 percent applies. [E7]")
    r = system.answer_query("fee?", LEX)
    assert r["sentences"][0]["citations"] == [] and r["sentences"][0]["support_status"] == cit.UNSUPPORTED
