"""
Unit tests for hybrid/query_gate.py (v1 prototype). The three roadmap worked
examples are run through explain_gate and their full output is printed, so the
actual classification can be read, not just asserted.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import unittest
from query_gate import classify_query, graph_weight, explain_gate

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CASE_A = "Has my last recharge of ₹299 gone through, and when does my plan expire?"
CASE_B = "Can the company keep sending me promotional SMS after I've registered for DND?"
CASE_C = "My KYC is showing pending — does that mean my number will get disconnected, and what do I do?"


def show(label, question):
    result = explain_gate(question)
    print(f"\n{label}: {json.dumps(result, ensure_ascii=False, indent=2)}")
    return result


class TestQueryGate(unittest.TestCase):

    def test_case_a_recharge_plan(self):
        r = show("Case (a)", CASE_A)
        self.assertTrue(r["classification"]["needs_personal_data"])
        self.assertIn(r["classification"]["concept_hint"], ("Recharge", "Plan Catalogue"))
        self.assertEqual(r["graph_weight"], 0.5)

    def test_case_b_dnd_policy(self):
        # Prediction: personal=False. The concept hint is reported, not forced.
        r = show("Case (b)", CASE_B)
        self.assertFalse(r["classification"]["needs_personal_data"])
        hint = r["classification"]["concept_hint"]
        self.assertEqual(r["graph_weight"], 0.0 if hint is None else 0.15)

    def test_case_c_kyc(self):
        r = show("Case (c)", CASE_C)
        self.assertTrue(r["classification"]["needs_personal_data"])
        self.assertEqual(r["classification"]["concept_hint"], "KYC & Identity Verification")
        self.assertEqual(r["graph_weight"], 0.5)

    def test_edge_empty_string(self):
        r = show("Edge - empty string", "")
        self.assertFalse(r["classification"]["needs_personal_data"])
        self.assertIsNone(r["classification"]["concept_hint"])
        self.assertEqual(r["graph_weight"], 0.0)

    def test_edge_no_signal(self):
        r = show("Edge - no signal", "What is the capital of India?")
        self.assertFalse(r["classification"]["needs_personal_data"])
        self.assertIsNone(r["classification"]["concept_hint"])
        self.assertEqual(r["graph_weight"], 0.0)

    def test_weight_tiers(self):
        self.assertEqual(graph_weight({"needs_personal_data": True, "concept_hint": "Recharge"}), 0.5)
        self.assertEqual(graph_weight({"needs_personal_data": False, "concept_hint": "Recharge"}), 0.15)
        self.assertEqual(graph_weight({"needs_personal_data": True, "concept_hint": None}), 0.0)

    def test_howto_is_not_personal(self):
        self.assertFalse(classify_query("How do I port to another operator?")["needs_personal_data"])

    def test_none_input(self):
        self.assertEqual(explain_gate(None)["graph_weight"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
