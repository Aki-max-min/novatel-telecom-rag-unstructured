"""
Unit tests for the Phase 8a post-hoc fixes. Every sentence below is NEW: none appears in
route_benchmark.json, the retrieval benchmarks or earlier test files.
"""

import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from query_gate import MISSING_CONCEPT_TARGETS, classify_query, explain_gate  # noqa: E402
from router import detect_intents, has_policy_component, route_query  # noqa: E402

HAVE_RETRIEVAL = all(importlib.util.find_spec(m) for m in ("faiss", "sentence_transformers"))


class TestGateFixes(unittest.TestCase):

    def test_plural_personal_facts(self):
        # the original defect: singular was personal, plural was not
        self.assertTrue(classify_query("Are my ticket still open?")["needs_personal_data"])
        self.assertTrue(classify_query("Are my tickets still open?")["needs_personal_data"])
        for q in ("Have my payments been received?", "Why are my bills so high?",
                  "Where are my invoices?", "Did my recharges all succeed?", "Are my plans still valid?"):
            self.assertTrue(classify_query(q)["needs_personal_data"], q)

    def test_a_promotional_does_not_match_promo(self):
        spam = explain_gate("Why do I keep getting marketing calls on my phone?")
        self.assertIsNone(spam["classification"]["concept_hint"])
        self.assertEqual(spam["graph_weight"], 0.0)
        dnd = explain_gate("Is it legal for unsolicited text messages to reach a number on the DND list?")
        self.assertIsNone(dnd["classification"]["concept_hint"])
        self.assertEqual(dnd["graph_weight"], 0.0)
        offers = classify_query("What promotional offers are on recharge?")
        self.assertEqual(offers["concept_hint"], "Offers & Promotions")
        self.assertEqual(classify_query("Is there a promo code for new customers?")["concept_hint"],
                         "Offers & Promotions")
        self.assertEqual(classify_query("Which promotions run this month?")["concept_hint"], "Offers & Promotions")

    def test_b_bare_number_is_not_personal(self):
        self.assertFalse(classify_query("How many digits are in a mobile number?")["needs_personal_data"])
        self.assertFalse(classify_query("I wonder what a number series means")["needs_personal_data"])
        self.assertTrue(classify_query("Why is my mobile number blocked?")["needs_personal_data"])
        self.assertTrue(classify_query("Is my number registered?")["needs_personal_data"])

    def test_d_concept_hints(self):
        self.assertEqual(MISSING_CONCEPT_TARGETS, [])
        self.assertEqual(classify_query("Will my handset work with 5G and VoLTE?")["concept_hint"],
                         "Device Compatibility")
        self.assertEqual(classify_query("Can a phone from another brand use 5G here?")["concept_hint"],
                         "Device Compatibility")
        self.assertEqual(classify_query("Do you sell a business plan for my company?")["concept_hint"],
                         "Enterprise & Business Services")
        self.assertEqual(classify_query("What connectivity does a corporate SIM bundle give?")["concept_hint"],
                         "Enterprise & Business Services")
        # without the second group the single-keyword hint is unchanged
        self.assertEqual(classify_query("How strong is 5G coverage downtown?")["concept_hint"], "Network Coverage")


class TestRouterFixes(unittest.TestCase):

    def test_c_policy_cue_generalisation(self):
        for q in ("Which certificates do I need to submit?", "Which forms must I provide at the store?",
                  "What papers should I bring along?", "Which copies do I have to carry?"):
            self.assertTrue(has_policy_component(q), q)
        self.assertFalse(has_policy_component("When does my plan expire?"))

    def test_c_subscribe_is_a_subscription_intent(self):
        self.assertIn("subscription", detect_intents("I subscribed to a pack last week"))
        self.assertIn("subscription", detect_intents("I want to subscribe again"))

    def test_plural_intents_route_structured(self):
        plan = route_query("Are my tickets still open?", 1042)
        self.assertEqual((plan.route, plan.outcome), ("structured", "answer"))
        self.assertIn("tickets", plan.structured_intents)

    def test_e_unrecognised_personal_request_flag(self):
        plan = route_query("What is going on with my account lately?", 1042)
        print(f"\nunrecognised: {plan.as_dict()}")
        self.assertEqual((plan.route, plan.outcome), ("unstructured", "answer"))
        self.assertTrue(plan.unrecognised_personal_request)
        for control in ("How do I fix my SIM?", "What is the penalty for early closure?"):
            self.assertFalse(route_query(control, 1042).unrecognised_personal_request, control)
        # a recognised intent is never flagged
        self.assertFalse(route_query("Are my tickets still open?", 1042).unrecognised_personal_request)

    def test_f_third_party_possessive_refused(self):
        for q in ("What is my mother's last recharge?", "What are my wife's pending bills?",
                  "Show my husband's plan expiry date", "My friend's balance please"):
            plan = route_query(q, 1042)
            self.assertEqual(plan.outcome, "refuse_other_customer", q)
            self.assertEqual(plan.refusal_reason, "third_party_reference", q)
        # refusal does not depend on being logged in
        self.assertEqual(route_query("What is my mother's last recharge?", None).outcome, "refuse_other_customer")

    def test_f_howto_about_a_third_party_is_not_refused(self):
        for q in ("How can I recharge for my mother?", "How do I pay a bill for my father?"):
            plan = route_query(q, 1042)
            self.assertEqual((plan.route, plan.outcome), ("unstructured", "answer"), q)
            self.assertIsNone(plan.refusal_reason)
            self.assertFalse(plan.unrecognised_personal_request)

    def test_f_kin_word_without_my_is_not_third_party(self):
        self.assertEqual(route_query("Is a mother allowed to add a child to a family plan?", 1042).outcome, "answer")


@unittest.skipUnless(HAVE_RETRIEVAL, "needs faiss + sentence-transformers (rag-api environment)")
class TestPipelineFlags(unittest.TestCase):

    def test_flag_reaches_blocked_and_trace_while_documents_still_run(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query("What is going on with my account lately?", 1042)
        self.assertIn("unrecognised_personal_request", out["blocked"])
        self.assertTrue(out["trace"]["unrecognised_personal_request"])
        self.assertEqual(out["route_plan"]["outcome"], "answer")
        self.assertEqual(out["facts"], [])
        self.assertTrue(out["documents"])

    def test_third_party_refusal_returns_nothing(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query("What is my mother's last recharge?", 1042)
        self.assertEqual((out["facts"], out["documents"]), ([], []))
        self.assertEqual(out["blocked"], ["refuse_other_customer"])
        self.assertEqual(out["trace"]["refusal_reason"], "third_party_reference")


if __name__ == "__main__":
    unittest.main(verbosity=2)
