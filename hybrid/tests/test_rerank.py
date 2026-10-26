"""
Unit tests for hybrid/rerank.py and hybrid/pipeline.py.

CountingScorer / FailingScorer are TEST DOUBLES injected via the `model=` parameter
to observe how many pairs reach the scorer; the module itself never mocks scores.
The pipeline test uses the real default path (model=None) and reports honestly
whether the real CrossEncoder ran or the fallback triggered.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import copy
import unittest
import warnings
from rerank import controlled_rerank
from pipeline import run_hybrid_retrieval

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def make(record_id, score, method="vector"):
    return {"source": "unstructured", "record_id": record_id, "dataset": "kb",
            "category": "TEST", "score": score, "retrieval_method": method,
            "content": f"content of {record_id}", "metadata": {"document_id": record_id}}


class CountingScorer:
    """Scores by the trailing number in the content, and records every pair it sees."""
    def __init__(self):
        self.pairs_seen = 0

    def predict(self, pairs):
        self.pairs_seen += len(pairs)
        return [float(p[1].rsplit("_", 1)[1]) for p in pairs]


class FailingScorer:
    def predict(self, pairs):
        raise RuntimeError("model unavailable (test double)")


def vector_list():
    return [make("doc_A", 0.90), make("doc_B", 0.80), make("doc_C", 0.70)]


def graph_list():
    return [make("doc_C", 5.0, "graph"), make("doc_D", 3.0, "graph"), make("doc_A", 1.0, "graph")]


class TestControlledRerank(unittest.TestCase):

    def test_max_pool_enforced(self):
        # 30 candidates ranked by fusion_score; doc_NN has fusion_score 1 - NN/100.
        cands = []
        for i in range(30):
            c = make(f"cand_{i}", 0.5)
            c["fusion_score"] = 1 - i / 100
            c["original_score"] = 0.5
            cands.append(c)
        scorer = CountingScorer()
        out = controlled_rerank("q", cands, max_pool=20, top_k=5, model=scorer, mode="override")
        print(f"\nmax_pool test: candidates_in=30, candidates_actually_processed={scorer.pairs_seen}")
        self.assertEqual(scorer.pairs_seen, 20)
        # Only the fusion top-20 (cand_0..cand_19) may appear; scorer prefers high numbers -> cand_19 first.
        self.assertEqual([c["record_id"] for c in out],
                         ["cand_19", "cand_18", "cand_17", "cand_16", "cand_15"])

    def test_fewer_than_pool_reranks_all(self):
        scorer = CountingScorer()
        cands = [make(f"c_{i}", 0.5) for i in range(3)]
        out = controlled_rerank("q", cands, max_pool=20, top_k=5, model=scorer, mode="override")
        self.assertEqual(scorer.pairs_seen, 3)
        self.assertEqual(len(out), 3)

    def test_scores_preserved_and_rerank_score_added(self):
        c = make("c_1", 0.5)
        c["fusion_score"], c["original_score"] = 0.0123, 0.77
        snapshot = copy.deepcopy([c])
        out = controlled_rerank("q", [c], model=CountingScorer())
        print(f"preserved fields: fusion_score={out[0]['fusion_score']} original_score={out[0]['original_score']} rerank_score={out[0]['rerank_score']}")
        self.assertEqual(out[0]["fusion_score"], 0.0123)
        self.assertEqual(out[0]["original_score"], 0.77)
        self.assertEqual(out[0]["rerank_score"], 1.0)
        self.assertEqual([c], snapshot)  # input dict itself untouched
        self.assertNotIn("rerank_score", c)

    def test_fallback_is_loud_and_unscored(self):
        cands = [make(f"c_{i}", 0.5) for i in range(8)]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = controlled_rerank("q", cands, top_k=5, model=FailingScorer())
        self.assertEqual([c["record_id"] for c in out], [f"c_{i}" for i in range(5)])
        self.assertTrue(all(c["rerank_score"] is None for c in out))
        self.assertTrue(all(c["rerank_status"].startswith("FALLBACK") for c in out))
        self.assertTrue(any("NOT PERFORMED" in str(w.message) for w in caught))

    def test_pipeline_three_questions(self):
        questions = [
            ("recharge", "Has my last recharge of ₹299 gone through, and when does my plan expire?"),
            ("DND", "Can the company keep sending me promotional SMS after I've registered for DND?"),
            ("KYC", "My KYC is showing pending — does that mean my number will get disconnected, and what do I do?"),
        ]
        print("\nrun_hybrid_retrieval (default model path):")
        for label, q in questions:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                out = run_hybrid_retrieval(q, vector_list(), graph_list(), top_k=5)
            status = "REAL CrossEncoder" if out[0]["rerank_score"] is not None else "FALLBACK (not reranked)"
            print(f"  {label}: {status}")
            for c in out:
                print(f"    {c['record_id']}: fusion_score={c['fusion_score']!r} rerank_score={c['rerank_score']!r} sources={c['fusion_sources']}")
            # Phase 8a: the DND question now gets graph weight 0.0, so graph-only doc_D is excluded
            self.assertEqual(len(out), 3 if label == "DND" else 4)

    def test_pipeline_end_to_end_with_scorer(self):
        scorer = CountingScorer()
        # contents end in letters, so give the scorer numeric contents
        v = [make(f"d_{i}", 0.9 - i / 100) for i in range(3)]
        out = run_hybrid_retrieval("What is the capital of India?", v, [], top_k=2, model=scorer, mode="override")
        self.assertEqual([c["record_id"] for c in out], ["d_2", "d_1"])
        self.assertEqual(scorer.pairs_seen, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
