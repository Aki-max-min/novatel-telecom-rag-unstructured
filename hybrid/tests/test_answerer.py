"""
Tests for hybrid/answer.py. No network anywhere: the LLM path is exercised with FAKE clients only.
Structured-only questions run against the real read-only database; document channels are injected through
a stub pipeline so these tests need neither faiss nor the CrossEncoder.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from answer import (AnthropicClient, ExtractiveAnswerer, LLMAnswerer, answer_question,  # noqa: E402
                    render_context_for_llm)
from context import assemble_context  # noqa: E402
from pipeline import run_hybrid_query  # noqa: E402
from router import route_query  # noqa: E402
from structured_adapter import fetch_customer_facts  # noqa: E402

REFUND = {
    "source": "unstructured", "record_id": "FAQ_C20_040_chunk_000", "dataset": "novatel_synthetic",
    "category": "C20", "score": 1.0, "retrieval_method": "vector",
    "content": ("# Refund timelines\n**Document ID:** FAQ_C20_040\n"
                "Question: How long do refunds to my bank account typically take?\n"
                "Answer: Once approved, refunds to source (card/UPI/net banking) generally reflect within 5-7 working "
                "days, subject to your bank's processing time. Refunds to NovaTel Wallet are typically instant to "
                "24 hours. Contact care if the money has not arrived."),
    "metadata": {"document_id": "FAQ_C20_040", "title": "Refund timelines"},
}
KYC_DOC = {
    "source": "unstructured", "record_id": "FAQ_C17_034_chunk_000", "dataset": "novatel_synthetic",
    "category": "C17", "score": 1.0, "retrieval_method": "vector",
    "content": ("Answer: Complete re-verification in store with your original ID or through Video KYC in the app. "
                "Failure to complete requested re-verification within the notified window may result in service "
                "suspension per licence conditions."),
    "metadata": {"document_id": "FAQ_C17_034", "title": "KYC re-verification"},
}


def stub_pipeline(docs):
    """A pipeline that uses the real router and adapter but returns the given documents (no retrieval models)."""
    def run(question, customer_id=None, as_of=None):
        plan = route_query(question, customer_id)
        facts = []
        if plan.outcome == "answer" and plan.route in ("structured", "both"):
            facts = fetch_customer_facts(customer_id, plan.structured_intents, as_of=as_of)
        documents = []
        if plan.outcome != "refuse_other_customer" and (plan.route in ("unstructured", "both")
                                                         or plan.outcome == "needs_identity"):
            documents = docs
        blocked = [] if plan.outcome == "answer" else [plan.outcome]
        if plan.unrecognised_personal_request:
            blocked.append("unrecognised_personal_request")
        return {"route_plan": plan.as_dict(), "facts": facts, "documents": documents, "blocked": blocked,
                "documents_are_generic": plan.outcome == "needs_identity" and bool(documents),
                "trace": {"refusal_reason": plan.refusal_reason}}
    return run


def ask(question, customer_id=None, as_of=None, answerer=None, docs=()):
    return answer_question(question, customer_id, as_of, answerer, pipeline=stub_pipeline(list(docs)))


class TestExtractiveAnchors(unittest.TestCase):

    def test_1042_recharge(self):
        out = ask("Did my last recharge go through?", 1042)
        a = out["answer"]
        print(f"\n[1042 recharge] {a}")
        for needle in ("4254", "399.00", "SUCCESS", "2026-04-17"):
            self.assertIn(needle, a)
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertEqual(out["mode"], "extractive")
        self.assertEqual(out["citations"]["F1"], "structured_sql:recharge_transactions:4254")

    def test_1042_kyc_pending_with_no_kyc_records_row(self):
        out = ask("Is my KYC complete?", 1042)
        a = out["answer"]
        print(f"\n[1042 kyc] {a}")
        self.assertIn("Pending", a)
        self.assertIn("no kyc_records row", a)
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertIn("no kyc_records row", out["notices"])

    def test_1042_subscription_expiry_passed_as_of(self):
        out = ask("When does my plan expire?", 1042, as_of="2026-10-06")
        a = out["answer"]
        print(f"\n[1042 plan, as_of 2026-10-06] {a}")
        self.assertIn("2026-10-03", a)
        self.assertIn("stored status Active", a)
        self.assertIn("has passed", a)
        self.assertNotIn("days remaining", a.lower())
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertIn("expiry_passed", out["notices"])

    def test_1042_subscription_without_as_of_makes_no_expiry_claim(self):
        a = ask("When does my plan expire?", 1042)["answer"]
        self.assertNotIn("has passed", a)
        self.assertNotIn("not passed", a)

    def test_1056_recharge_failed(self):
        out = ask("Did my last recharge go through?", 1056)
        a = out["answer"]
        print(f"\n[1056 recharge] {a}")
        for needle in ("4996", "949.00", "FAILED"):
            self.assertIn(needle, a)
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])

    def test_1829_invoice_records_disagree(self):
        out = ask("Is my latest bill paid?", 1829)
        a = out["answer"]
        print(f"\n[1829 invoice] {a}")
        self.assertIn("6740", a)
        self.assertIn("Unpaid", a)
        self.assertIn("581.65", a)
        self.assertIn("records disagree", a)
        self.assertIn("billing agent can confirm", a)
        self.assertNotIn("is paid", a.replace("stored payment_status", ""))  # it never declares which is right
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertIn("status_ledger_mismatch", out["notices"])

    def test_no_tickets_is_stated_not_invented(self):
        out = ask("Do I have any open tickets?", 1015)
        self.assertIn("no tickets", out["answer"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])

    def test_tickets_listed_with_stored_statuses(self):
        out = ask("Do I have any open tickets?", 1042)
        for needle in ("12099", "12323", "11335", "Open", "InProgress"):
            self.assertIn(needle, out["answer"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])


class TestDocumentsNoticesAndSilence(unittest.TestCase):

    def test_documents_are_quoted_verbatim_with_citations(self):
        out = ask("How long do refunds to source take?", None, docs=[REFUND])
        a = out["answer"]
        print(f"\n[refund docs] {a}")
        self.assertIn("5-7 working days", a)
        self.assertIn("[D1]", a)
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertEqual(out["citations"]["D1"], "document:FAQ_C20_040")

    def test_silence_rule_instead_of_guessing(self):
        out = ask("Will my number get disconnected, and what is the penalty?", None, docs=[REFUND])
        a = out["answer"]
        self.assertIn("The retrieved documents don't state anything about disconnect.", a)
        self.assertIn("The retrieved documents don't state anything about penalty.", a)
        # a term that IS in the snippet gets no silence sentence
        out2 = ask("How many days until the refund reaches me?", None, docs=[REFUND])
        self.assertNotIn("don't state anything about days", out2["answer"])
        self.assertNotIn("don't state anything about refund", out2["answer"])

    def test_suspension_term_in_documents_is_not_reported_as_silent(self):
        out = ask("My KYC is showing pending - will my number be suspended, and what do I do?", None, docs=[KYC_DOC])
        self.assertNotIn("don't state anything about suspend", out["answer"])
        self.assertIn("service suspension per licence conditions", out["answer"])  # the sentence is quoted

    def test_needs_identity_wording_and_generic_documents(self):
        out = ask("Did my last recharge go through?", None, docs=[REFUND])
        a = out["answer"]
        print(f"\n[no customer] {a}")
        self.assertIn("once you are identified", a)
        self.assertIn("general and is not about your account", a)
        self.assertNotIn("4254", a)
        self.assertNotIn("[F", a)
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertIn("needs_identity", out["notices"])

    def test_refusal_is_plain_cites_nothing_and_leaks_nothing(self):
        out = ask("What is the balance on 9756865116?", 1042, docs=[REFUND])
        a = out["answer"]
        print(f"\n[other number] {a}")
        self.assertIn("signed-in account", a)
        self.assertEqual(out["citations"], {})
        for leak in ("9756865116", "4996", "949.00", "FAILED"):
            self.assertNotIn(leak, a)
        self.assertNotIn("not allowed", a.lower())  # no accusation
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertIn("refuse_other_customer", out["notices"])

    def test_unrecognised_personal_request_wording(self):
        out = ask("What is going on with my account lately?", 1042, docs=[REFUND])
        self.assertIn("couldn't tell which account detail you meant", out["answer"])
        self.assertIn("unrecognised_personal_request", out["notices"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])


class TestPostFixes(unittest.TestCase):
    """Phase 9c post-hoc fixes found by reading the first-run sample answers."""

    def test_no_customer_never_claims_that_nothing_was_found(self):
        out = ask("When does my plan expire and what was my last recharge?", None, docs=[REFUND])
        self.assertIn("needs_identity", out["notices"])
        self.assertNotIn("I found no", out["answer"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        # an identified customer with genuinely no rows still gets the explicit statement
        self.assertIn("I found no tickets", ask("Do I have any open tickets?", 1015)["answer"])

    def test_markdown_table_fragments_are_not_quoted(self):
        table_doc = dict(REFUND, content=("Key Details | Detail | Value | |---|---| | Refund to source | 5-7 working days "
                                          "after approval, subject to bank processing | Troubleshooting. "
                                          "Refunds to source generally reflect within 5-7 working days after "
                                          "approval depending on your bank."))
        out = ask("How long do refunds to source take?", None, docs=[table_doc])
        self.assertNotIn("|", out["answer"])
        self.assertIn("generally reflect within 5-7 working days", out["answer"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])


class FakeClient:
    def __init__(self, text):
        self.text, self.calls = text, []

    def complete(self, system, user):
        self.calls.append((system, user))
        return self.text


class TestLLMPath(unittest.TestCase):
    """Fake clients only - no network."""

    Q = "Did my last recharge go through?"

    def test_invented_amount_falls_back_to_extractive(self):
        client = FakeClient("Your latest recharge was for 499.00 with status SUCCESS [F1].")
        out = ask(self.Q, 1042, answerer=LLMAnswerer(client))
        self.assertEqual(out["mode"], "llm_fallback")
        self.assertIn("399.00", out["answer"])
        self.assertNotIn("499.00", out["answer"])
        self.assertTrue(any(p.startswith("R3") for p in out["verifier"]["llm_problems"]))
        self.assertTrue(out["verifier"]["ok"])

    def test_missing_citations_fall_back_to_extractive(self):
        client = FakeClient("Your latest recharge was for 399.00 with status SUCCESS.")
        out = ask(self.Q, 1042, answerer=LLMAnswerer(client))
        self.assertEqual(out["mode"], "llm_fallback")
        self.assertTrue(any(p.startswith("R1") for p in out["verifier"]["llm_problems"]))
        self.assertIn("[F1]", out["answer"])

    def test_grounded_llm_answer_is_accepted(self):
        text = "Yes - your latest recharge (ID 4254) was for 399.00 and its status is SUCCESS [F1]."
        client = FakeClient(text)
        out = ask(self.Q, 1042, answerer=LLMAnswerer(client))
        self.assertEqual(out["mode"], "llm")
        self.assertEqual(out["answer"], text)
        self.assertTrue(out["verifier"]["ok"])
        system, user = client.calls[0]
        self.assertIn("ONLY the numbered context", system)
        self.assertIn("[F1]", user)

    def test_llm_context_rendering_uses_ids_and_masks_msisdn(self):
        ctx = assemble_context(stub_pipeline([REFUND])("Did my last recharge go through?", 1042))
        rendered = render_context_for_llm("q", ctx)
        self.assertIn("[F1]", rendered)
        self.assertNotIn("9146794714", rendered)

    def test_anthropic_client_needs_key_and_model_and_has_no_default_model(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as e:
                AnthropicClient()
            self.assertIn("ANTHROPIC_API_KEY", str(e.exception))
            self.assertIn("NOVATEL_LLM_MODEL", str(e.exception))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}, clear=True):
            with self.assertRaises(RuntimeError) as e:
                AnthropicClient()
            self.assertIn("NOVATEL_LLM_MODEL", str(e.exception))
            self.assertNotIn("ANTHROPIC_API_KEY and", str(e.exception))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k", "NOVATEL_LLM_MODEL": "m"}, clear=True):
            client = AnthropicClient()  # construction makes no network call
            self.assertEqual(client.model, "m")

    def test_llm_is_off_by_default(self):
        out = ask(self.Q, 1042)
        self.assertEqual(out["mode"], "extractive")
        self.assertIsInstance(ExtractiveAnswerer(), ExtractiveAnswerer)

    def test_no_network_modules_are_imported_by_these_tests(self):
        self.assertNotIn("anthropic", sys.modules)  # the SDK is imported lazily, only for a real call


if __name__ == "__main__":
    unittest.main(verbosity=2)
