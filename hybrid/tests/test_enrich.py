"""
KG fixes 2, step 4 (tests first): query enrichment, our own module hybrid/enrich.py (no import of Person A's code).
enrich_query(question) -> (enriched_text, trace). Deterministic rules over the existing vocabulary only; at most 6 appended terms; original words
never removed or reordered; nothing recognised -> enriched == original. The enriched text reaches the FAISS query ONLY (CrossEncoder, gate,
router and the structured parser keep the ORIGINAL question). ENRICH_ENABLED defaults to False and, when off, the output (trace included) is
byte-identical to the output without this feature; the trace field "enrichment" exists only when it is on.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import enrich  # noqa: E402
import pipeline  # noqa: E402
import retrievers  # noqa: E402
from test_one_link_mechanism import FakeCorpus, FakePersonA, tiny_index  # noqa: E402


class TestEnrichQuery(unittest.TestCase):

    def test_identity_when_nothing_is_recognised(self):
        for q in ("Hello there, how are you today?", "zzz qqq plain words", ""):
            text, trace = enrich.enrich_query(q)
            self.assertEqual(text, q)
            self.assertEqual(trace["appended"], [])
            self.assertEqual(trace["concepts"], [])

    def test_original_words_are_kept_in_order_and_terms_are_appended(self):
        q = "How long does it take to port my number to NovaTel?"
        text, trace = enrich.enrich_query(q)
        self.assertTrue(text.startswith(q))
        self.assertGreater(len(trace["appended"]), 0)
        self.assertEqual(text, q + " " + " ".join(trace["appended"]))
        self.assertIn("Number Portability", trace["concepts"])
        self.assertIn("Number Portability", trace["appended"])           # the canonical name

    def test_a_term_already_in_the_question_is_not_repeated(self):
        q = "What is number portability and how does portability work?"
        _, trace = enrich.enrich_query(q)
        low = q.lower()
        for term in trace["appended"]:
            self.assertNotIn(term.lower(), low)
        self.assertEqual(len(trace["appended"]), len({t.lower() for t in trace["appended"]}))

    def test_cap_of_six_appended_terms(self):
        q = ("My recharge failed, I want a refund, my bill and invoice look wrong, I need roaming, a new SIM, number porting, "
             "KYC, a complaint, broadband outage, fraud and a plan change")
        text, trace = enrich.enrich_query(q)
        self.assertLessEqual(len(trace["appended"]), enrich.MAX_APPENDED_TERMS)
        self.assertEqual(enrich.MAX_APPENDED_TERMS, 6)
        self.assertGreaterEqual(len(trace["concepts"]), 3)
        self.assertTrue(text.startswith(q))

    def test_appended_terms_come_from_the_existing_vocabulary_only(self):
        from knowledge_graph.concept_bridge import concept_vocabulary, load_crosswalk
        from knowledge_graph.content_extractor import CONCEPT_DICTIONARY
        from query_gate import KEYWORD_CONCEPT_MAP
        allowed = ({n.lower() for n in concept_vocabulary(load_crosswalk())} | {k.lower() for k in KEYWORD_CONCEPT_MAP}
                   | {p.lower() for ph in CONCEPT_DICTIONARY["Service"].values() for p in ph})
        for q in ("How do I get a refund for a failed recharge?", "Is roaming active on my SIM?", "Why is my broadband down?"):
            _, trace = enrich.enrich_query(q)
            for term in trace["appended"]:
                self.assertIn(term.lower(), allowed, term)

    def test_deterministic(self):
        q = "I was charged twice for the same recharge, how do I get the extra amount back?"
        self.assertEqual(enrich.enrich_query(q), enrich.enrich_query(q))

    def test_trace_shape(self):
        _, trace = enrich.enrich_query("How do I update my KYC?")
        self.assertEqual(sorted(trace), ["appended", "concepts", "enriched"])
        self.assertIsInstance(trace["enriched"], bool)
        self.assertEqual(trace["enriched"], bool(trace["appended"]))

    def test_none_and_non_string_inputs_do_not_raise(self):
        self.assertEqual(enrich.enrich_query(None)[0], None)

    def test_module_does_not_import_person_a_code(self):
        src = Path(enrich.__file__).read_text(encoding="utf-8")
        self.assertNotIn("integration", src.replace("integration of", ""))


class FakeRetriever:
    def __init__(self):
        self.queries = []

    def search(self, question, depth=10):
        self.queries.append(question)
        return [{"document_id": d, "chunk_id": f"{d}_chunk_000", "title": d, "category": "", "score": s}
                for d, s in (("A", 0.9), ("B", 0.8))]


class RecordingScorer:
    def __init__(self):
        self.questions = set()

    def predict(self, pairs):
        self.questions |= {p[0] for p in pairs}
        return [0.0] * len(pairs)


Q = "How do refunds work after a failed recharge?"


class TestPipelineWiring(unittest.TestCase):

    def run_query(self, enabled):
        retriever, scorer = FakeRetriever(), RecordingScorer()
        with mock.patch.object(pipeline, "ENRICH_ENABLED", enabled), \
                mock.patch.object(retrievers, "get_graph_index_safe", lambda: (tiny_index(), None)), \
                mock.patch.object(retrievers, "load_vector_context",
                                  lambda: {"retriever": retriever, "corpus": FakeCorpus, "person_a": FakePersonA}):
            out = pipeline.run_hybrid_query(Q, None, model=scorer)
        return out, retriever, scorer

    def test_default_is_off(self):
        self.assertIs(pipeline.ENRICH_ENABLED, False)

    def test_off_sends_the_original_question_and_adds_nothing_to_the_trace(self):
        out, retriever, _ = self.run_query(False)
        self.assertEqual(retriever.queries, [Q])
        self.assertNotIn("enrichment", out["trace"])

    def test_off_output_is_byte_identical_across_runs(self):
        a, _, _ = self.run_query(False)
        b, _, _ = self.run_query(False)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))

    def test_on_enriches_the_faiss_query_only(self):
        out, retriever, scorer = self.run_query(True)
        enriched, trace = enrich.enrich_query(Q)
        self.assertNotEqual(enriched, Q)
        self.assertEqual(retriever.queries, [enriched])
        self.assertEqual(scorer.questions, {Q})                          # the CrossEncoder sees the ORIGINAL question
        self.assertEqual(out["trace"]["enrichment"]["appended"], trace["appended"])

    def test_on_leaves_routing_and_structured_facts_unchanged(self):
        off, _, _ = self.run_query(False)
        on, _, _ = self.run_query(True)
        self.assertEqual(on["route_plan"], off["route_plan"])
        self.assertEqual(on["facts"], off["facts"])
        self.assertEqual(on["trace"]["graph_weight"], off["trace"]["graph_weight"])
        self.assertEqual(on["trace"]["concept_hint"], off["trace"]["concept_hint"])

    def test_nothing_recognised_means_the_same_faiss_query_even_when_on(self):
        retriever, scorer = FakeRetriever(), RecordingScorer()
        with mock.patch.object(pipeline, "ENRICH_ENABLED", True), \
                mock.patch.object(retrievers, "get_graph_index_safe", lambda: (tiny_index(), None)), \
                mock.patch.object(retrievers, "load_vector_context",
                                  lambda: {"retriever": retriever, "corpus": FakeCorpus, "person_a": FakePersonA}):
            out = pipeline.run_hybrid_query("zzz qqq plain words", None, model=scorer)
        self.assertEqual(retriever.queries, ["zzz qqq plain words"])
        self.assertEqual(out["trace"]["enrichment"]["appended"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
