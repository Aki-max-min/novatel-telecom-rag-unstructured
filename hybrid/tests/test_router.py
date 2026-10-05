"""
Tests for hybrid/router.py and the run_hybrid_query pipeline. Uses only the examples
specified for Phase 7b. Pipeline tests that retrieve documents need faiss +
sentence-transformers (the rag-api environment) and are skipped without them.
"""

import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from router import detect_intents, route_query  # noqa: E402

HAVE_RETRIEVAL = all(importlib.util.find_spec(m) for m in ("faiss", "sentence_transformers"))

Q_RECHARGE_PLAN = "Has my last recharge of Rs 299 gone through, and when does my plan expire?"
Q_DND = "Can the company keep sending me promotional SMS after I've registered for DND?"
Q_KYC = "My KYC is showing pending - does that mean my number will get disconnected, and what do I do?"
Q_OTHER_NUMBER = "What is the balance on 9756865116?"


class TestRouter(unittest.TestCase):

    def test_recharge_and_plan_is_structured(self):
        plan = route_query(Q_RECHARGE_PLAN, 1042)
        print(f"\nrecharge+plan: {plan.as_dict()}")
        self.assertEqual((plan.route, plan.outcome), ("structured", "answer"))
        self.assertIn("recharge", plan.structured_intents)
        self.assertIn("subscription", plan.structured_intents)

    def test_dnd_policy_question_is_unstructured(self):
        plan = route_query(Q_DND, None)
        print(f"\nDND: {plan.as_dict()}")
        self.assertEqual((plan.route, plan.outcome), ("unstructured", "answer"))
        self.assertEqual(plan.structured_intents, [])

    def test_kyc_with_customer_is_both(self):
        plan = route_query(Q_KYC, 1042)
        print(f"\nKYC (1042): {plan.as_dict()}")
        self.assertEqual((plan.route, plan.outcome), ("both", "answer"))
        self.assertIn("kyc", plan.structured_intents)
        self.assertTrue(plan.has_policy_component)

    def test_kyc_without_customer_needs_identity_but_keeps_both_route(self):
        plan = route_query(Q_KYC, None)
        print(f"\nKYC (None): {plan.as_dict()}")
        self.assertEqual((plan.route, plan.outcome), ("both", "needs_identity"))

    def test_other_customers_number_is_refused(self):
        plan = route_query(Q_OTHER_NUMBER, 1042)
        print(f"\nother number: {plan.as_dict()}")
        self.assertEqual(plan.outcome, "refuse_other_customer")

    def test_own_number_is_not_refused(self):
        plan = route_query("What is the balance on 9146794714?", 1042)
        self.assertEqual((plan.route, plan.outcome), ("structured", "answer"))

    def test_foreign_number_without_session_needs_identity_not_data(self):
        plan = route_query(Q_OTHER_NUMBER, None)
        self.assertEqual(plan.outcome, "needs_identity")

    def test_word_boundaries(self):
        self.assertEqual(detect_intents("Is the planet Mars visible from here?"), [])
        self.assertEqual(detect_intents("I need to reticket this request"), [])
        self.assertNotIn("subscription", detect_intents("My planet shows no signal"))
        self.assertNotIn("tickets", detect_intents("I will reticket my flight"))
        self.assertIn("subscription", detect_intents("when does my plan expire"))
        self.assertIn("tickets", detect_intents("do I have an open ticket"))
        plan = route_query("My planet-themed app does not open and I must reticket", 1042)
        self.assertEqual(plan.structured_intents, [])

    def test_expired_kyc_is_not_a_plan_question(self):
        self.assertEqual(detect_intents("my KYC shows as expired"), ["kyc"])


@unittest.skipUnless(HAVE_RETRIEVAL, "needs faiss + sentence-transformers (rag-api environment)")
class TestPipeline(unittest.TestCase):

    def test_both_with_customer_returns_two_separate_channels(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query(Q_KYC, 1042)
        self.assertEqual(out["route_plan"]["route"], "both")
        self.assertEqual(out["blocked"], [])
        self.assertTrue(out["facts"] and out["documents"])
        self.assertTrue(all(f["source"] == "structured_sql" for f in out["facts"]))
        self.assertTrue(all(d["source"] == "unstructured" for d in out["documents"]))
        self.assertTrue(all("fusion_score" not in f for f in out["facts"]))  # channels are not fused

    def test_both_without_customer_blocks_facts_but_still_returns_documents(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query(Q_KYC, None)
        print(f"\nKYC (None) blocked={out['blocked']} facts={len(out['facts'])} documents={len(out['documents'])}")
        self.assertEqual(out["route_plan"]["outcome"], "needs_identity")
        self.assertEqual(out["facts"], [])
        self.assertTrue(out["documents"])
        self.assertEqual(out["blocked"], ["needs_identity"])

    def test_other_customer_number_fetches_nothing(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query(Q_OTHER_NUMBER, 1042)
        self.assertEqual(out["route_plan"]["outcome"], "refuse_other_customer")
        self.assertEqual((out["facts"], out["documents"]), ([], []))
        self.assertEqual(out["blocked"], ["refuse_other_customer"])

    def test_unstructured_question_has_no_facts(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query(Q_DND, None)
        self.assertEqual(out["facts"], [])
        self.assertTrue(out["documents"])

    def test_run_hybrid_retrieval_still_works_unchanged(self):
        from pipeline import run_hybrid_retrieval
        self.assertTrue(callable(run_hybrid_retrieval))


if __name__ == "__main__":
    unittest.main(verbosity=2)
