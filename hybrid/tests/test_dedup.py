"""
Unit tests for hybrid/dedup.py -- evidence dedup + context selection.
Includes the real Q13 case from Phase 3 (MAN_APP_001 chunks crowding out FAQ_C13_025).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import copy
import unittest
from dedup import dedupe_candidates, select_context


def make(record_id, score, document_id):
    return {
        "source": "unstructured", "record_id": record_id, "dataset": "kb",
        "category": "APP", "score": score, "retrieval_method": "dense",
        "content": f"placeholder for {record_id}",
        "metadata": {"document_id": document_id},
    }


def q13_input():
    return [
        make("MAN_APP_001_chunk_000", 0.7017, "MAN_APP_001"),
        make("SOP_C13_APP_ACCESS_ISSUES_chunk_000", 0.6919, "SOP_C13_APP_ACCESS_ISSUES"),
        make("MAN_APP_001_chunk_001", 0.6774, "MAN_APP_001"),
        make("FAQ_C13_025_chunk_000", 0.6428, "FAQ_C13_025"),
    ]


class TestDedup(unittest.TestCase):

    def test_q13_ground_truth(self):
        cands = q13_input()
        out = dedupe_candidates(cands)
        self.assertEqual(len(out), 3)
        self.assertEqual([c["metadata"]["document_id"] for c in out],
                         ["MAN_APP_001", "SOP_C13_APP_ACCESS_ISSUES", "FAQ_C13_025"])
        self.assertEqual(out[0]["score"], 0.7017)

        top3 = select_context(cands, top_k=3)
        self.assertEqual(len(top3), 3)
        self.assertEqual([c["record_id"] for c in top3], [c["record_id"] for c in out])
        self.assertIn("FAQ_C13_025", [c["metadata"]["document_id"] for c in top3])

    def test_no_duplicates(self):
        cands = [make("A_chunk_000", 0.9, "A"), make("B_chunk_000", 0.8, "B"),
                 make("C_chunk_000", 0.7, "C")]
        self.assertEqual(dedupe_candidates(cands), cands)

    def test_all_same_document(self):
        cands = [make("D_chunk_000", 0.5, "D"), make("D_chunk_001", 0.9, "D"),
                 make("D_chunk_002", 0.7, "D")]
        out = dedupe_candidates(cands)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["record_id"], "D_chunk_001")
        self.assertEqual(out[0]["score"], 0.9)

    def test_does_not_mutate_input(self):
        cands = q13_input()
        snapshot = copy.deepcopy(cands)
        dedupe_candidates(cands)
        select_context(cands, top_k=2)
        self.assertEqual(cands, snapshot)

    def test_key_fallbacks(self):
        no_meta = {"record_id": "X_chunk_000", "score": 0.4, "metadata": {}}
        no_meta2 = {"record_id": "X_chunk_007", "score": 0.6}
        plain = {"record_id": "Y", "score": 0.5}
        out = dedupe_candidates([no_meta, no_meta2, plain])
        self.assertEqual([c["record_id"] for c in out], ["X_chunk_007", "Y"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
