"""
Unit tests for retriever.py -- confirms exact_lookup, exact_filter,
aggregate_count, and search() all return correctly-shaped Common Result
Schema objects, and that normalization is applied correctly.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from datetime import date
from retriever import StructuredRetriever

REQUIRED_SCHEMA_FIELDS = {
    "source", "record_id", "dataset", "category",
    "score", "retrieval_method", "content", "metadata"
}


class TestStructuredRetriever(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.retriever = StructuredRetriever()

    @classmethod
    def tearDownClass(cls):
        cls.retriever.close()

    def test_exact_lookup_returns_one_result(self):
        res = self.retriever.exact_lookup("customer_master", 1001)
        self.assertEqual(len(res["results"]), 1)

    def test_exact_lookup_result_matches_common_schema(self):
        res = self.retriever.exact_lookup("customer_master", 1001)
        result = res["results"][0]
        self.assertTrue(REQUIRED_SCHEMA_FIELDS.issubset(result.keys()))
        self.assertEqual(result["source"], "structured")
        self.assertEqual(result["retrieval_method"], "exact_lookup")
        self.assertEqual(result["dataset"], "customer_master")

    def test_exact_lookup_normalizes_types_in_metadata(self):
        res = self.retriever.exact_lookup("customer_master", 1001)
        metadata = res["results"][0]["metadata"]
        self.assertIsInstance(metadata["customer_id"], int)
        self.assertIsInstance(metadata["dob"], date)

    def test_exact_lookup_missing_id_returns_no_results(self):
        res = self.retriever.exact_lookup("customer_master", 999999999)
        self.assertEqual(len(res["results"]), 0)

    def test_exact_filter_respects_top_k(self):
        res = self.retriever.exact_filter("invoices", "customer_id", 1001, top_k=2)
        self.assertLessEqual(len(res["results"]), 2)

    def test_exact_filter_all_results_match_filter(self):
        res = self.retriever.exact_filter("customer_master", "status", "Active", top_k=50)
        for r in res["results"]:
            self.assertEqual(r["metadata"]["status"], "Active")

    def test_aggregate_count_matches_manual_filter_count(self):
        agg_res = self.retriever.aggregate_count("recharge_transactions", "status", "FAILED")
        agg_count = agg_res["results"][0]["metadata"]["count"]

        filter_res = self.retriever.exact_filter("recharge_transactions", "status", "FAILED", top_k=100000)
        self.assertEqual(agg_count, len(filter_res["results"]))

    def test_aggregate_count_result_matches_common_schema(self):
        res = self.retriever.aggregate_count("recharge_transactions", "status", "FAILED")
        result = res["results"][0]
        self.assertTrue(REQUIRED_SCHEMA_FIELDS.issubset(result.keys()))
        self.assertEqual(result["retrieval_method"], "aggregate")

    def test_search_returns_results_for_valid_question(self):
        res = self.retriever.search("What plan is customer 1001 on?")
        self.assertGreater(len(res["results"]), 0)
        self.assertIn("parsed_query", res)

    def test_search_returns_empty_with_note_for_unresolvable_question(self):
        res = self.retriever.search("asdkjaslkdj random gibberish query")
        self.assertEqual(len(res["results"]), 0)
        self.assertIn("note", res)

    def test_all_results_have_positive_latency(self):
        res = self.retriever.exact_lookup("customer_master", 1001)
        self.assertGreaterEqual(res["latency_sec"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)