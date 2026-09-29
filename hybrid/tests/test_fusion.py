"""
Unit tests for hybrid/fusion.py. Uses the hand-checkable worked example:
vector = [A, B, C] (scores 0.9/0.8/0.7), graph = [C, D, A] (scores 5.0/3.0/1.0 -
a different scale on purpose, to prove fusion is rank-based).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import copy
import unittest
from fusion import fuse_candidates, fuse_and_select
from knowledge_graph.graph_augmented_retrieval import RRF_K

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def make(record_id, score, method):
    return {"source": "unstructured", "record_id": record_id, "dataset": "kb",
            "category": "TEST", "score": score, "retrieval_method": method,
            "content": f"placeholder {record_id}", "metadata": {"document_id": record_id}}


def vector_list():
    return [make("doc_A", 0.90, "vector"), make("doc_B", 0.80, "vector"), make("doc_C", 0.70, "vector")]


def graph_list():
    return [make("doc_C", 5.0, "graph"), make("doc_D", 3.0, "graph"), make("doc_A", 1.0, "graph")]


class TestFusion(unittest.TestCase):

    def test_k_matches_validated_value(self):
        self.assertEqual(RRF_K, 60)

    def test_weight_zero_excludes_graph_entirely(self):
        out = fuse_candidates(vector_list(), graph_list(), 0.0)
        ids = [c["record_id"] for c in out]
        print(f"\nTest 1 (weight=0.0): output order {ids}, doc_D_present: {'doc_D' in ids}")
        self.assertEqual(ids, ["doc_A", "doc_B", "doc_C"])
        self.assertNotIn("doc_D", ids)
        self.assertTrue(all(c["fusion_sources"] == ["vector"] for c in out))

    def test_weight_half_breakdown(self):
        k, w = RRF_K, 0.5
        expected = {
            "doc_A": (1 / (k + 1), w / (k + 3)),
            "doc_B": (1 / (k + 2), 0.0),
            "doc_C": (1 / (k + 3), w / (k + 1)),
            "doc_D": (0.0, w / (k + 2)),
        }
        print(f"\nTest 2 (weight=0.5, k={k}):")
        print(f"  doc_A: vector_contribution=1/({k}+1)={expected['doc_A'][0]!r}, graph_contribution=0.5/({k}+3)={expected['doc_A'][1]!r}, total={sum(expected['doc_A'])!r}")
        print(f"  doc_B: vector_contribution=1/({k}+2)={expected['doc_B'][0]!r}, graph_contribution=0 (not in graph list), total={sum(expected['doc_B'])!r}")
        print(f"  doc_C: vector_contribution=1/({k}+3)={expected['doc_C'][0]!r}, graph_contribution=0.5/({k}+1)={expected['doc_C'][1]!r}, total={sum(expected['doc_C'])!r}")
        print(f"  doc_D: vector_contribution=0 (not in vector list), graph_contribution=0.5/({k}+2)={expected['doc_D'][1]!r}, total={sum(expected['doc_D'])!r}")

        out = fuse_candidates(vector_list(), graph_list(), w)
        print("  final order:")
        for c in out:
            print(f"    {c['record_id']}: fusion_score={c['fusion_score']!r} sources={c['fusion_sources']}")

        self.assertEqual([c["record_id"] for c in out], ["doc_A", "doc_C", "doc_B", "doc_D"])
        for c in out:
            self.assertAlmostEqual(c["fusion_score"], sum(expected[c["record_id"]]), places=15)
        by_id = {c["record_id"]: c for c in out}
        self.assertEqual(by_id["doc_A"]["fusion_sources"], ["vector", "graph"])
        self.assertEqual(by_id["doc_D"]["fusion_sources"], ["graph"])

    def test_inputs_not_mutated(self):
        v, g = vector_list(), graph_list()
        v0, g0 = copy.deepcopy(v), copy.deepcopy(g)
        fuse_candidates(v, g, 0.5)
        self.assertEqual((v, g), (v0, g0))

    def test_fuse_and_select_three_questions(self):
        cases = [
            ("recharge", "Has my last recharge of ₹299 gone through, and when does my plan expire?", 0.5,
             ["doc_A", "doc_C", "doc_B", "doc_D"]),
            ("DND", "Can the company keep sending me promotional SMS after I've registered for DND?", 0.15,
             ["doc_A", "doc_C", "doc_B", "doc_D"]),
            ("KYC", "My KYC is showing pending — does that mean my number will get disconnected, and what do I do?", 0.5,
             ["doc_A", "doc_C", "doc_B", "doc_D"]),
        ]
        from query_gate import explain_gate
        print("\nfuse_and_select (top_k=5):")
        for label, question, weight, order in cases:
            used = explain_gate(question)["graph_weight"]
            out = fuse_and_select(vector_list(), graph_list(), question, top_k=5)
            print(f"  {label}: weight_used={used} (Phase 2 reported {weight})")
            for c in out:
                print(f"    {c['record_id']}: fusion_score={c['score']!r} sources={c['fusion_sources']}")
            self.assertEqual(used, weight)
            self.assertEqual([c["record_id"] for c in out], order)

    def test_fuse_and_select_no_signal_excludes_graph(self):
        out = fuse_and_select(vector_list(), graph_list(), "What is the capital of India?")
        self.assertEqual([c["record_id"] for c in out], ["doc_A", "doc_B", "doc_C"])

    def test_fuse_and_select_dedupes_chunks(self):
        v = [make("D1_chunk_000", 0.9, "vector"), make("D1_chunk_001", 0.8, "vector"), make("D2_chunk_000", 0.7, "vector")]
        for c in v:
            c["metadata"] = {"document_id": c["record_id"].split("_chunk")[0]}
        out = fuse_and_select(v, [], "What is the capital of India?", top_k=2)
        self.assertEqual([c["metadata"]["document_id"] for c in out], ["D1", "D2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
