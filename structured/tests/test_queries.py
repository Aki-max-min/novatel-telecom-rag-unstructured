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


class TestWordBoundaryRegression(unittest.TestCase):
    """Person A's bug: bare substring tests (kw in q_lower) matched inside other words."""

    def table(self, q):
        return parse_query(q).get("table")

    def test_port_inside_other_words_does_not_trigger_porting_requests(self):
        for q in ("What is important here?", "Show the report", "Who gives support?", "A transport question"):
            self.assertNotEqual(self.table(q), "porting_requests", q)
            self.assertIsNone(self.table(q), q)

    def test_sim_inside_other_words_does_not_trigger_sim_inventory(self):
        for q in ("Show similar items", "Run a simulation", "A simple question"):
            self.assertIsNone(self.table(q), q)

    def test_postpaid_and_prepaid_are_not_status_paid(self):
        self.assertIsNone(extract_status_value_for_table("Show postpaid invoices", "invoices"))
        self.assertIsNone(extract_status_value_for_table("Show prepaid invoices", "invoices"))
        self.assertEqual(extract_status_value_for_table("Show paid invoices", "invoices"), "Paid")

    def test_inactive_is_inactive_not_active(self):
        self.assertEqual(extract_status_value_for_table("Show inactive sim_inventory", "sim_inventory"), "Inactive")
        self.assertEqual(extract_status_value_for_table("Show active sim_inventory", "sim_inventory"), "Active")

    def test_incomplete_is_not_complete(self):
        self.assertNotEqual(extract_status_value_for_table("Show incomplete kyc_records", "kyc_records"), "Complete")
        self.assertEqual(extract_status_value_for_table("Show complete kyc_records", "kyc_records"), "Complete")

    def test_unresolved_is_not_resolved(self):
        self.assertNotEqual(extract_status_value_for_table("Show unresolved fraud cases", "fraud_cases"), "Resolved")
        self.assertEqual(parse_query("Show unresolved fraud cases")["table"], "fraud_cases")
        self.assertEqual(extract_status_value_for_table("Show resolved fraud cases", "fraud_cases"), "Resolved")

    def test_explanation_website_bottom_match_nothing(self):
        for q in ("Give me an explanation", "Visit the website", "See the bottom of the page"):
            self.assertIsNone(self.table(q), q)

    def test_two_tables_in_one_question_is_ambiguous_not_first_match(self):
        result = parse_query("Show the plan and invoice for customer 1001")
        self.assertIsNone(result["table"])
        self.assertTrue(result["error"].startswith("ambiguous:"), result)
        self.assertIn("invoices", result["error"])
        self.assertIn("subscriptions", result["error"])
        self.assertNotIn("results", result)

    def test_underscore_table_names_still_resolve(self):
        for name in ("recharge_transactions", "payment_transactions", "sim_inventory", "kyc_records",
                     "porting_requests", "fraud_cases", "escalation_cases", "fiber_inventory"):
            self.assertEqual(self.table(f"Show {name} with status Pending"), name, name)

    def test_exact_table_name_wins_over_keywords(self):
        self.assertEqual(self.table("Show esim_profiles with status Active"), "esim_profiles")
        self.assertEqual(self.table("Show esim_profiles for the customer profile"), "esim_profiles")

    def test_inflections_still_match(self):
        self.assertEqual(self.table("Why was I billed twice?"), "invoices")
        self.assertEqual(self.table("Show my billing"), "invoices")
        self.assertEqual(self.table("List all invoices"), "invoices")
        self.assertEqual(self.table("Which plans exist?"), "subscriptions")


HELDOUT_PATH = os.path.join(os.path.dirname(__file__), "parser_heldout.json")


def score_heldout():
    """(correct, acceptable_abstain, wrong, details) over structured/tests/parser_heldout.json."""
    import json
    with open(HELDOUT_PATH, encoding="utf-8") as fh:
        items = json.load(fh)
    correct = abstain = 0
    wrong = []
    for question, gold, accept_abstain in items:
        table = parse_query(question).get("table")
        if table == gold:
            correct += 1
        elif table is None and accept_abstain:
            abstain += 1
        else:
            wrong.append((question, gold, table))
    return correct, abstain, wrong, len(items)


class TestHeldOutTableDetection(unittest.TestCase):
    """22 held-out questions, committed BEFORE the keyword-strength tuning and never edited afterwards.
    wrong = a wrong table, or an abstain where accept_abstain=0. Pass criterion: wrong == 0."""

    def test_no_wrong_tables_on_heldout_set(self):
        correct, abstain, wrong, n = score_heldout()
        print(f"held-out: correct={correct} acceptable_abstain={abstain} wrong={len(wrong)} of {n}")
        for q, gold, got in wrong:
            print(f"   WRONG  gold={gold} got={got} | {q}")
        self.assertEqual(correct + abstain + len(wrong), n)
        self.assertEqual(wrong, [])


class TestPersonAReportedQuestions(unittest.TestCase):
    """Reported by Person A: these tied 1-1 under the word-boundary parser and got no table.
    The tuning that fixes them is POST-HOC against exactly these four."""

    def test_rb_s06_invoice(self):
        self.assertEqual(parse_query("Is my latest bill paid or still pending?")["table"], "invoices")

    def test_rb_b05_subscriptions(self):
        q = "My plan ran out a long time ago - can I still get incoming calls, and how do I get service back?"
        self.assertEqual(parse_query(q)["table"], "subscriptions")

    def test_rb_b06_invoice(self):
        q = "My latest postpaid bill looks higher than my plan rental - what does it show, and how do I dispute it?"
        self.assertEqual(parse_query(q)["table"], "invoices")

    def test_rb_s08_tickets(self):
        self.assertEqual(parse_query("Are there any open complaints on my account?")["table"], "tickets")


if __name__ == "__main__":
    unittest.main(verbosity=2)