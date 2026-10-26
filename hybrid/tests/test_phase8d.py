"""
Phase 8d tests: conditional / hypothetical frames vs status-query frames, and documents
surviving a missing identity. Every sentence below is NEW; a scan test asserts that none of them
appears in any JSON file under hybrid/benchmark/ or ingestion/.
"""

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from query_gate import classify_query  # noqa: E402
from router import route_query  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HAVE_RETRIEVAL = all(importlib.util.find_spec(m) for m in ("faiss", "sentence_transformers"))

NON_PERSONAL = [
    "Suppose I port my number out, do I lose my balance?",
    "What if I recharge twice in one day?",
    "If I add a data pack after I top up, does validity change?",
    "What happens if I pay my invoice late?",
]
PERSONAL = [
    "Did my recharge go through?",
    "Have I been charged for last month's bill?",
    "When does my plan expire?",
    "What is the status of my ticket?",
    "How much do I owe on my invoice?",
]


class TestFrames(unittest.TestCase):

    def test_hypothetical_frames_are_not_personal(self):
        for q in NON_PERSONAL:
            c = classify_query(q)
            self.assertFalse(c["needs_personal_data"], q)
            self.assertTrue(c["hypothetical_frame"], q)

    def test_status_query_frames_are_personal(self):
        for q in PERSONAL:
            c = classify_query(q)
            self.assertTrue(c["needs_personal_data"], q)
            self.assertFalse(c["hypothetical_frame"], q)

    def test_router_sends_hypotheticals_to_documents_with_a_policy_component(self):
        for q in NON_PERSONAL:
            plan = route_query(q, 1042)
            self.assertEqual((plan.route, plan.outcome), ("unstructured", "answer"), q)
            self.assertTrue(plan.has_policy_component, q)
            self.assertEqual(plan.structured_intents, [], q)

    def test_router_sends_status_queries_to_the_structured_source(self):
        for q in PERSONAL:
            plan = route_query(q, 1042)
            self.assertIn(plan.route, ("structured", "both"), q)
            self.assertTrue(plan.structured_intents, q)

    def test_original_conditional_failures_are_policy_questions(self):
        # the three failures observed on the pre-Phase-8 gate
        for q in ("Can both offers be applied when I recharge once?", "What happens if I change my plan mid-cycle?",
                  "If I pay my bill late, is there a penalty?"):
            self.assertFalse(classify_query(q)["needs_personal_data"], q)

    def test_fact_words_without_a_first_person_anchor_are_not_personal(self):
        # Phase 8e replacement (1/2) for the Phase 8d bare-fact test; approved by the user.
        for q in ("What is a plan?", "Do plans include 5G?"):
            self.assertFalse(classify_query(q)["needs_personal_data"], q)

    def test_possessive_plus_fact_is_an_assertion_and_therefore_personal(self):
        """Phase 8e replacement (2/2); approved by the user.

        "I like my plan" is an ASSERTION (possessive + fact term in a clause that is not hypothetical
        and has no policy cue), so it is personal by Phase 8e design. The asymmetry behind that choice:
        a false "personal" call costs one read-only fetch for the already-authenticated customer
        (documents are never withheld since Phase 8d), whereas a false "impersonal" call silently drops
        the customer's own facts. This replaces the Phase 8d rule (anchor + fact + status frame all
        required) that asserted the opposite for this sentence.
        """
        self.assertTrue(classify_query("I like my plan")["needs_personal_data"])

    def test_frame_test_sentences_are_not_in_any_benchmark_file(self):
        sentences = [s.lower() for s in NON_PERSONAL + PERSONAL]
        files = (list((REPO_ROOT / "hybrid" / "benchmark").rglob("*.json"))
                 + list((REPO_ROOT / "ingestion").rglob("*.json")))
        self.assertGreater(len(files), 2)
        findings = []
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            try:
                text += "\n" + json.dumps(json.loads(text), ensure_ascii=False).lower()
            except ValueError:
                pass
            for sentence in sentences:
                if sentence in text:
                    findings.append(f"{path.relative_to(REPO_ROOT)}: {sentence}")
        self.assertEqual(findings, [])


@unittest.skipUnless(HAVE_RETRIEVAL, "needs faiss + sentence-transformers (rag-api environment)")
class TestDocumentsSurviveMissingIdentity(unittest.TestCase):

    def test_structured_route_without_customer_still_returns_generic_documents(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query("Did my recharge go through?", None)
        self.assertEqual(out["route_plan"]["route"], "structured")
        self.assertEqual(out["route_plan"]["outcome"], "needs_identity")
        self.assertEqual(out["facts"], [])
        self.assertTrue(out["documents"])
        self.assertTrue(out["documents_are_generic"])
        self.assertIn("needs_identity", out["blocked"])

    def test_refusal_returns_neither_facts_nor_documents(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query("What is the balance on 9756865116?", 1042)
        self.assertEqual(out["route_plan"]["outcome"], "refuse_other_customer")
        self.assertEqual((out["facts"], out["documents"]), ([], []))
        self.assertFalse(out["documents_are_generic"])

    def test_answered_question_is_not_marked_generic(self):
        from pipeline import run_hybrid_query
        out = run_hybrid_query("Is my invoice paid?", 1042)
        self.assertEqual(out["route_plan"]["outcome"], "answer")
        self.assertFalse(out["documents_are_generic"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
