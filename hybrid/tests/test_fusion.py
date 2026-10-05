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


def make_chunk(record_id, score, method, document_id=None):
    """Candidate whose document key is derived from record_id unless document_id is given."""
    c = make(record_id, score, method)
    c["metadata"] = {"document_id": document_id} if document_id else {}
    return c


class TestDocumentLevelKeying(unittest.TestCase):
    """Fusion is document-level: best (earliest) rank per document per list."""

    def test_chunk_and_bare_id_fuse_as_one_document(self):
        k = RRF_K
        vector = [make_chunk("X_chunk_000", 0.9, "vector"), make_chunk("Y_chunk_000", 0.8, "vector"),
                  make_chunk("X_chunk_001", 0.7, "vector")]
        graph = [make_chunk("Z", 4.0, "graph"), make_chunk("X", 3.0, "graph")]  # X is graph rank 2
        out = fuse_candidates(vector, graph, 0.5)
        xs = [c for c in out if c["fusion_doc_key"] == "X"]
        self.assertEqual(len(xs), 1)
        expected = 1 / (k + 1) + 0.5 / (k + 2)  # vector best rank 1 + graph rank 2; 2nd chunk adds nothing
        print(f"\ntest (a): X fusion_score={xs[0]['fusion_score']!r} expected 1/61 + 0.5/62 = {expected!r}")
        self.assertAlmostEqual(xs[0]["fusion_score"], expected, places=15)
        self.assertEqual(xs[0]["fusion_sources"], ["vector", "graph"])
        self.assertEqual(xs[0]["record_id"], "X_chunk_000")  # representative: best vector chunk
        self.assertEqual(len([c for c in out if c["fusion_doc_key"] == "Y"]), 1)

    def test_two_chunks_of_one_vector_document_appear_once(self):
        vector = [make_chunk("D_chunk_000", 0.9, "vector"), make_chunk("D_chunk_001", 0.8, "vector")]
        out = fuse_candidates(vector, [], 0.5)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["fusion_score"], 1 / (RRF_K + 1), places=15)

    def test_weight_zero_still_excludes_graph_only_documents(self):
        vector = [make_chunk("X_chunk_000", 0.9, "vector")]
        graph = [make_chunk("W", 5.0, "graph"), make_chunk("X", 1.0, "graph")]
        out = fuse_candidates(vector, graph, 0.0)
        self.assertEqual([c["fusion_doc_key"] for c in out], ["X"])
        self.assertEqual(out[0]["fusion_sources"], ["vector"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
