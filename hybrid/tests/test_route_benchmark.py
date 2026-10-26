"""
Checks hybrid/benchmark/route_benchmark.json: composition, schema, document ids,
and that every expected_structured value re-derives from the SQLite database
(using SQL written independently of the builder).
"""

import json
import sqlite3
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH = REPO_ROOT / "hybrid" / "benchmark" / "route_benchmark.json"
DB_PATH = REPO_ROOT / "data" / "processed" / "structured" / "novatel_structured.db"
CHUNKS = REPO_ROOT / "data" / "vectorstore" / "chunk_metadata.json"

FIELDS = {"question_id", "question", "customer_id", "expected_route", "expected_outcome",
          "expected_structured", "expected_document_ids", "notes"}
PK = {"customer_master": "customer_id", "subscriptions": "subscription_id",
      "recharge_transactions": "recharge_id", "tickets": "ticket_id", "invoices": "invoice_id",
      "kyc_records": "kyc_id", "payment_transactions": "transaction_id"}


def same(a, b):
    """Equal, treating numeric strings and numbers alike (the DB stores everything as TEXT)."""
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


class TestRouteBenchmark(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.questions = json.loads(BENCH.read_text(encoding="utf-8"))["questions"]
        cls.db = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        cls.doc_ids = {e["document_id"] for e in json.loads(CHUNKS.read_text(encoding="utf-8"))}

    def test_counts(self):
        qs = self.questions
        structured = [q for q in qs if q["expected_route"] == "structured" and q["expected_outcome"] == "answer"]
        unstructured = [q for q in qs if q["expected_route"] == "unstructured"]
        both = [q for q in qs if q["expected_route"] == "both"]
        safety = [q for q in qs if q["expected_outcome"] != "answer"]
        self.assertEqual((len(structured), len(unstructured), len(both), len(safety)), (8, 8, 6, 2))
        self.assertEqual(len(qs), 24)
        self.assertEqual(len({q["question_id"] for q in qs}), 24)
        self.assertEqual({q["expected_outcome"] for q in safety}, {"needs_identity", "refuse_other_customer"})

    def test_schema(self):
        for q in self.questions:
            self.assertEqual(set(q), FIELDS, q["question_id"])
            self.assertIn(q["expected_route"], ("structured", "unstructured", "both"))
            self.assertIn(q["expected_outcome"], ("answer", "needs_identity", "refuse_other_customer"))
            self.assertIsInstance(q["expected_structured"], list)
            self.assertIsInstance(q["expected_document_ids"], list)
            for item in q["expected_structured"]:
                self.assertEqual(set(item), {"table", "record_id", "field", "value"})

    def test_route_content_consistency(self):
        for q in self.questions:
            if q["expected_outcome"] != "answer":
                self.assertEqual((q["expected_structured"], q["expected_document_ids"]), ([], []))
            elif q["expected_route"] == "structured":
                self.assertTrue(q["expected_structured"] and not q["expected_document_ids"])
                self.assertIsNotNone(q["customer_id"])
            elif q["expected_route"] == "unstructured":
                self.assertTrue(q["expected_document_ids"] and not q["expected_structured"])
                self.assertIsNone(q["customer_id"])
            else:
                self.assertTrue(q["expected_structured"] and q["expected_document_ids"])
                self.assertIsNotNone(q["customer_id"])

    def test_safety_cases(self):
        by_id = {q["question_id"]: q for q in self.questions}
        self.assertIsNone(by_id["RB_X01"]["customer_id"])
        self.assertEqual(by_id["RB_X01"]["expected_outcome"], "needs_identity")
        self.assertEqual(by_id["RB_X02"]["customer_id"], 1042)
        self.assertEqual(by_id["RB_X02"]["expected_outcome"], "refuse_other_customer")
        self.assertIn("9756865116", by_id["RB_X02"]["question"])
        owner = self.db.execute("select customer_id from customer_master where msisdn='9756865116'").fetchone()[0]
        self.assertEqual(int(owner), 1056)

    def test_document_ids_exist(self):
        for q in self.questions:
            for doc in q["expected_document_ids"]:
                self.assertIn(doc, self.doc_ids, f"{q['question_id']}: {doc}")

    def test_structured_values_rederive_from_sql(self):
        checked = 0
        for q in self.questions:
            for item in q["expected_structured"]:
                table, rid, field = item["table"], item["record_id"], item["field"]
                if field == "count_for_customer":
                    actual = self.db.execute(f"select count(*) from {table} where customer_id=?",
                                             (str(q["customer_id"]),)).fetchone()[0]
                elif field == "sum_amount_success_for_invoice":
                    actual = self.db.execute("select sum(cast(amount as real)) from payment_transactions "
                                             "where invoice_id=? and status='SUCCESS'", (str(rid),)).fetchone()[0]
                    actual = round(actual, 2)
                else:
                    row = self.db.execute(f"select {field} from {table} where {PK[table]}=?", (str(rid),)).fetchone()
                    self.assertIsNotNone(row, f"{q['question_id']}: no {table} row {rid}")
                    actual = row[0]
                self.assertTrue(same(actual, item["value"]),
                                f"{q['question_id']} {table}.{field}[{rid}]: db={actual!r} benchmark={item['value']!r}")
                checked += 1
        self.assertEqual(checked, sum(len(q["expected_structured"]) for q in self.questions))

    def test_structured_rows_belong_to_the_asking_customer(self):
        """A personal fact must come from the customer's own row (no cross-customer ground truth)."""
        owner_col = {"customer_master": "customer_id", "subscriptions": "customer_id", "tickets": "customer_id",
                     "invoices": "customer_id", "kyc_records": "customer_id", "payment_transactions": "customer_id"}
        for q in self.questions:
            for item in q["expected_structured"]:
                table, rid = item["table"], item["record_id"]
                if rid is None:
                    continue
                if item["field"] == "sum_amount_success_for_invoice":
                    # record_id is an invoice id; every payment on it must belong to the asking customer
                    owners = {int(r[0]) for r in self.db.execute(
                        "select customer_id from payment_transactions where invoice_id=?", (str(rid),))}
                    self.assertEqual(owners, {q["customer_id"]}, f"{q['question_id']} payments on invoice {rid}")
                    continue
                if table == "recharge_transactions":
                    owner = self.db.execute("select c.customer_id from recharge_transactions r join customer_master c "
                                            "on c.msisdn=r.msisdn where r.recharge_id=?", (str(rid),)).fetchone()[0]
                else:
                    owner = self.db.execute(f"select {owner_col[table]} from {table} where {PK[table]}=?",
                                            (str(rid),)).fetchone()[0]
                self.assertEqual(int(owner), q["customer_id"], f"{q['question_id']} {table} {rid}")

    def test_unstructured_questions_not_copied_from_existing_benchmark(self):
        existing = json.loads((REPO_ROOT / "ingestion" / "retrieval_benchmark.json").read_text(encoding="utf-8"))
        existing = existing if isinstance(existing, list) else existing["questions"]
        old = {e["question"].strip().lower() for e in existing}
        for q in self.questions:
            if q["expected_route"] == "unstructured":
                self.assertNotIn(q["question"].strip().lower(), old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
