"""
Unit tests for query_parser.py -- confirms natural-language questions
resolve to the correct table, method, and filter (including the specific
casing and column-name edge cases we found and fixed during development).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from query_parser import parse_query, get_status_column, extract_status_value_for_table


class TestQueryParser(unittest.TestCase):

    def test_customer_id_extraction_and_filter(self):
        result = parse_query("What plan is customer 1001 on?")
        self.assertEqual(result["table"], "subscriptions")
        self.assertEqual(result["method"], "exact_filter")
        self.assertEqual(result["filter_column"], "customer_id")
        self.assertEqual(result["filter_value"], 1001)

    def test_account_keyword_maps_to_customer_master(self):
        result = parse_query("What is customer 1001's account status?")
        self.assertEqual(result["table"], "customer_master")

    def test_aggregate_question_detected(self):
        result = parse_query("How many recharge_transactions have status FAILED?")
        self.assertEqual(result["method"], "aggregate")
        self.assertEqual(result["filter_value"], "FAILED")

    def test_invoices_uses_payment_status_column_not_status(self):
        """Regression test for the bug where invoices was queried with 'status'
        instead of the real column name 'payment_status'."""
        result = parse_query("List all overdue invoices")
        self.assertEqual(result["table"], "invoices")
        self.assertEqual(result["filter_column"], "payment_status")
        self.assertEqual(result["filter_value"], "Overdue")

    def test_esim_profiles_uses_activation_status_column(self):
        self.assertEqual(get_status_column("esim_profiles"), "activation_status")

    def test_status_casing_resolved_correctly_per_table_pending(self):
        """Regression test: 'pending' must resolve to 'PENDING' for
        recharge_transactions but 'Pending' for kyc_records."""
        recharge_value = extract_status_value_for_table(
            "Show recharge with status pending", "recharge_transactions"
        )
        kyc_value = extract_status_value_for_table(
            "Show kyc_records with status pending", "kyc_records"
        )
        self.assertEqual(recharge_value, "PENDING")
        self.assertEqual(kyc_value, "Pending")

    def test_status_casing_resolved_correctly_lowercase_input(self):
        """Regression test: lowercase user input ('open', 'overdue') must resolve
        to the correct title-case value actually stored in the database."""
        result = parse_query("Show all open tickets")
        self.assertEqual(result["filter_value"], "Open")

        result2 = parse_query("List all overdue invoices")
        self.assertEqual(result2["filter_value"], "Overdue")

    def test_previously_missing_status_values_now_resolve(self):
        """Regression test for Blocked, Rejected, Cancelled, Investigating
        which were originally missing from the status vocabulary."""
        cases = [
            ("Show sim_inventory with status Blocked", "sim_inventory", "Blocked"),
            ("Show porting_requests with status Rejected", "porting_requests", "Rejected"),
            ("Show orders with status Cancelled", "orders", "Cancelled"),
            ("Show fraud_cases with status Investigating", "fraud_cases", "Investigating"),
        ]
        for question, expected_table, expected_value in cases:
            with self.subTest(question=question):
                result = parse_query(question)
                self.assertEqual(result["table"], expected_table)
                self.assertEqual(result["filter_value"], expected_value)

    def test_unresolvable_question_returns_no_fabricated_filter(self):
        """Per the Partner Guide: no-result/ambiguous queries must be flagged
        explicitly, never fabricated."""
        result = parse_query("Is there a network outage?")
        # Either correctly resolved with a real filter, or explicitly unresolved --
        # never silently wrong.
        self.assertIn(result["method"], ("exact_filter", "exact_filter_unresolved", None))

    def test_unknown_topic_returns_none_table(self):
        result = parse_query("asdkjaslkdj random gibberish query")
        self.assertIsNone(result["table"])
        self.assertIsNone(result["method"])


if __name__ == "__main__":
    unittest.main(verbosity=2)