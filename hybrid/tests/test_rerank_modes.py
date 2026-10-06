"""
Unit tests for the Phase 8b rerank variants (V0 override, V1/V2 rrf_blend, V3 protect_graph),
using a deterministic stub scorer: the score of a candidate is the number in its content.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rerank import DEFAULT_RERANK_MODE, controlled_rerank  # noqa: E402


class NumberScorer:
    def predict(self, pairs):
        return [float(p[1].rsplit("_", 1)[1]) for p in pairs]


def cand(name, fusion_score, rerank_value, sources):
    return {"record_id": name, "score": fusion_score, "fusion_score": fusion_score,
            "fusion_sources": sources, "content": f"text_{rerank_value}", "metadata": {"document_id": name}}


def pool():
    """Fusion order A,B,C,D,E,F. Stub rerank order (high first): F, E, D, C, B, A. D is graph-only."""
    return [cand("A", 0.60, 1, ["vector"]), cand("B", 0.50, 2, ["vector"]), cand("C", 0.40, 3, ["vector"]),
            cand("D", 0.30, 4, ["graph"]), cand("E", 0.20, 5, ["vector"]), cand("F", 0.10, 6, ["vector"])]


def ids(out):
    return [c["record_id"] for c in out]


class TestRerankModes(unittest.TestCase):

    def test_default_is_the_adopted_variant_v1(self):
        # Phase 8b: the pre-declared rule adopted V1 (rrf_blend, w=1.0)
        self.assertEqual(DEFAULT_RERANK_MODE, "rrf_blend")
        self.assertEqual(ids(controlled_rerank("q", pool(), top_k=3, model=NumberScorer())),
                         ids(controlled_rerank("q", pool(), top_k=3, model=NumberScorer(),
                                               mode="rrf_blend", blend_weight=1.0)))

    def test_override_v0_is_still_available(self):
        self.assertEqual(ids(controlled_rerank("q", pool(), top_k=3, model=NumberScorer(), mode="override")),
                         ["F", "E", "D"])

    def test_v1_rrf_blend_matches_hand_arithmetic(self):
        k = 60
        out = controlled_rerank("q", pool(), top_k=6, model=NumberScorer(), mode="rrf_blend", blend_weight=1.0)
        # rank_fusion A..F = 1..6 ; rank_rerank A..F = 6..1  -> every candidate sums 1/(k+i) + 1/(k+7-i)
        expected = {n: 1 / (k + i) + 1 / (k + 7 - i) for i, n in enumerate("ABCDEF", start=1)}
        for c in out:
            self.assertAlmostEqual(c["blend_score"], expected[c["record_id"]], places=15)
        # A (fusion 1, rerank 6) and F (fusion 6, rerank 1) tie exactly; ties break on rerank rank -> F first
        self.assertEqual(ids(out)[:2], ["F", "A"])
        # the blend pulls the fusion leaders up relative to override
        self.assertEqual(ids(controlled_rerank("q", pool(), top_k=3, model=NumberScorer(),
                                               mode="rrf_blend", blend_weight=1.0)), ["F", "A", "E"])

    def test_v2_weights_rerank_less(self):
        out = controlled_rerank("q", pool(), top_k=3, model=NumberScorer(), mode="rrf_blend", blend_weight=0.5)
        self.assertEqual(ids(out)[0], "A")  # fusion leader wins when rerank counts half

    def test_v3_reserves_a_slot_for_best_graph_only_in_fusion_top5(self):
        # override top-2 = F,E ; D is graph-only at fusion rank 4 (<=5) -> reserved
        out = controlled_rerank("q", pool(), top_k=2, model=NumberScorer(), mode="protect_graph")
        self.assertEqual(set(ids(out)), {"D", "F"})
        self.assertEqual(ids(out), ["F", "D"])  # final set ordered by rerank score

    def test_v3_equals_v0_when_graph_only_already_in_top_k(self):
        v0 = ids(controlled_rerank("q", pool(), top_k=3, model=NumberScorer(), mode="override"))
        v3 = ids(controlled_rerank("q", pool(), top_k=3, model=NumberScorer(), mode="protect_graph"))
        self.assertEqual(v0, v3)  # D already in the top 3

    def test_v3_equals_v0_without_a_graph_only_candidate_in_fusion_top5(self):
        p = pool()
        p[3]["fusion_sources"] = ["vector", "graph"]
        self.assertEqual(ids(controlled_rerank("q", p, top_k=2, model=NumberScorer(), mode="protect_graph")),
                         ids(controlled_rerank("q", p, top_k=2, model=NumberScorer(), mode="override")))

    def test_v3_ignores_graph_only_outside_fusion_top5(self):
        p = pool() + [cand("G", 0.05, 0, ["graph"])]  # fusion rank 7
        p[3]["fusion_sources"] = ["vector"]
        out = controlled_rerank("q", p, top_k=2, model=NumberScorer(), mode="protect_graph")
        self.assertEqual(ids(out), ["F", "E"])

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            controlled_rerank("q", pool(), model=NumberScorer(), mode="nope")

    def test_inputs_not_mutated(self):
        p = pool()
        snapshot = [dict(c) for c in p]
        for mode in ("override", "rrf_blend", "protect_graph"):
            controlled_rerank("q", p, top_k=3, model=NumberScorer(), mode=mode)
        self.assertEqual(p, snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
