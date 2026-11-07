"""
Tests for StructuredRetriever.fk_follow: parent record + its child rows through an allow-listed foreign key
("invoice 5001" -> payment_transactions.invoice_id, "ticket 11011" -> escalation_cases.ticket_id).
Cases come from join_cases.json (ids chosen by SQL in build_join_cases.py); expected rows are RECOMPUTED here
from the database, never typed.
"""

import json
import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from query_parser import extract_customer_id
from retriever import StructuredRetriever
from schema import TABLE_SCHEMAS

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.abspath(os.path.join(HERE, "..", "..", "data", "processed", "structured", "novatel_structured.db"))
CASES = json.load(open(os.path.join(HERE, "join_cases.json"), encoding="utf-8"))["cases"]
FK_COLUMN = {("invoices", "payment_transactions"): "invoice_id", ("tickets", "escalation_cases"): "ticket_id"}
NOTE_NEEDLE = {"empty_foreign_parent": "does not belong", "empty_unknown_parent": "not found",
               "empty_no_fk": "no foreign key", "empty_unscopable": "cannot scope", "empty_injection": "customer"}


class TestForeignKeyFollow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = StructuredRetriever()
        cls.db = sqlite3.connect(f"file:{DB.replace(os.sep, '/')}?mode=ro", uri=True)
        cls.db.row_factory = sqlite3.Row

    def expected_rows(self, case):
        pk = TABLE_SCHEMAS[case["parent_table"]]["primary_key"]
        parent = self.db.execute(f"SELECT * FROM {case['parent_table']} WHERE {pk} = ?", (case["parent_id"],)).fetchone()
        col = FK_COLUMN[(case["parent_table"], case["child_table"])]
        children = self.db.execute(f"SELECT * FROM {case['child_table']} WHERE {col} = ?", (case["parent_id"],)).fetchall()
        return dict(parent), [dict(c) for c in children], col

    def test_cases_file_has_at_least_8_cases_with_every_required_kind(self):
        self.assertGreaterEqual(len(CASES), 8)
        kinds = {c["expect"] for c in CASES}
        for needed in ("rows", "empty_foreign_parent", "empty_unknown_parent", "parent_only", "empty_no_fk", "empty_injection"):
            self.assertIn(needed, kinds)
        self.assertTrue({"invoice_with_payments", "ticket_with_escalation"} <= {c["name"] for c in CASES})

    def test_each_case(self):
        for case in CASES:
            with self.subTest(case=case["name"]):
                out = self.r.fk_follow(case["question"], customer_id=case["customer_id"])
                self.assertIsNotNone(out, "an FK question must be recognised")
                kind, results = case["expect"], out["results"]
                if kind == "rows":
                    parent, children, col = self.expected_rows(case)
                    customer = case["customer_id"] if case["customer_id"] is not None else int(extract_customer_id(case["question"]))
                    self.assertEqual(str(parent["customer_id"]), str(customer))
                    self.assertTrue(out["executed"])
                    self.assertEqual(results[0]["dataset"], case["parent_table"])
                    self.assertEqual(results[0]["record_id"], str(case["parent_id"]))
                    child_results = results[1:]
                    pk = TABLE_SCHEMAS[case["child_table"]]["primary_key"]
                    self.assertEqual(sorted(r["record_id"] for r in child_results), sorted(str(c[pk]) for c in children))
                    self.assertGreaterEqual(len(child_results), 1)
                    for r in child_results:
                        self.assertEqual(r["dataset"], case["child_table"])
                        self.assertEqual(r["metadata"]["relation"], f"fk:{case['parent_table']}.{col}")
                        self.assertEqual(str(r["metadata"][col]), str(case["parent_id"]))
                    self.assertEqual(out["relation"], f"fk:{case['parent_table']}.{col}")
                elif kind == "parent_only":
                    self.assertEqual(len(results), 1)
                    self.assertEqual(results[0]["record_id"], str(case["parent_id"]))
                    self.assertIn("no child rows", out["note"])
                    self.assertEqual(self.expected_rows(case)[1], [])
                else:
                    self.assertEqual(results, [])
                    self.assertIn(NOTE_NEEDLE[kind], out["note"].lower())

    def test_another_customers_rows_never_appear(self):
        for name in ("invoice_of_another_customer", "ticket_of_another_customer"):
            case = next(c for c in CASES if c["name"] == name)
            out = self.r.fk_follow(case["question"], customer_id=case["customer_id"])
            pk = TABLE_SCHEMAS[case["parent_table"]]["primary_key"]
            owner = self.db.execute(f"SELECT customer_id FROM {case['parent_table']} WHERE {pk} = ?",
                                    (case["parent_id"],)).fetchone()[0]
            self.assertNotEqual(str(owner), str(case["customer_id"]))
            self.assertEqual(out["results"], [])
            self.assertNotIn("TXN", json.dumps(out, default=str))

    def test_allowlist_comes_from_the_schema(self):
        from retriever import FK_CHILDREN
        for parent, children in FK_CHILDREN.items():
            for child, column in children:
                self.assertEqual(TABLE_SCHEMAS[child]["foreign_keys"][column], parent)
        self.assertIn(("payment_transactions", "invoice_id"), FK_CHILDREN["invoices"])
        self.assertIn(("escalation_cases", "ticket_id"), FK_CHILDREN["tickets"])

    def test_non_fk_questions_are_not_handled_here(self):
        self.assertIsNone(self.r.fk_follow("Show all open tickets"))
        self.assertIsNone(self.r.fk_follow("What plan is customer 1001 on?"))
        self.assertIsNone(self.r.fk_follow("Show invoice 5001 for customer 1001"))   # parent only, no child entity

    def test_search_routes_fk_questions_through_fk_follow(self):
        case = next(c for c in CASES if c["name"] == "invoice_with_payments")
        out = self.r.search(case["question"], top_k=10)
        self.assertGreaterEqual(len(out["results"]), 3)
        self.assertTrue(any(x["metadata"].get("relation") == "fk:invoices.invoice_id" for x in out["results"]))

    def test_injection_strings_in_any_position_never_widen_the_result(self):
        for evil in ("1001' OR '1'='1", "1001; DROP TABLE invoices", "x' UNION SELECT * FROM customer_master --"):
            out = self.r.fk_follow("For this customer, show invoice 5001 and the payment transactions against it",
                                   customer_id=evil)
            self.assertEqual(out["results"], [])
        self.assertGreater(self.db.execute("SELECT count(*) FROM invoices").fetchone()[0], 100)

    def test_existing_behaviour_is_unchanged(self):
        out = self.r.search("What plan is customer 1001 on?")
        self.assertEqual(out["parsed_query"]["table"], "subscriptions")


if __name__ == "__main__":
    unittest.main(verbosity=2)
