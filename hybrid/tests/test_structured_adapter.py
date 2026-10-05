"""
Tests for hybrid/structured_adapter.py: verified anchors, per-customer isolation
(zero leakage across 25 customers x every intent), read-only enforcement,
parameterised-SQL scan, data minimisation, and the no-category-join rule.
"""

import json
import os
import re
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from structured_adapter import INTENTS, fetch_customer_facts, open_readonly  # noqa: E402

HYBRID_DIR = Path(__file__).resolve().parents[1]
FORBIDDEN_KEYS = {"name", "dob", "email", "address"}


def by_record(facts):
    return {f["record_id"]: f for f in facts}


def walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_keys(v)


class TestAnchors(unittest.TestCase):

    def test_1042_kyc_pending_with_explicit_no_record_marker(self):
        recs = by_record(fetch_customer_facts(1042, ["kyc"]))
        self.assertEqual(recs["customer_master:1042"]["metadata"]["kyc_status"], "Pending")
        marker = recs["kyc_records:none"]
        self.assertEqual(marker["metadata"]["kyc_records_rows"], 0)
        self.assertIn("no kyc_records row", marker["content"])

    def test_1042_subscription_verbatim_and_as_of(self):
        f = by_record(fetch_customer_facts(1042, ["subscription"]))["subscriptions:3042"]
        md = f["metadata"]
        self.assertEqual((int(md["plan_id"]), md["expiry_date"], md["status"]), (2011, "2026-10-03", "Active"))
        self.assertIsNotNone(md["plan_name"])
        self.assertNotIn("derived", md)
        self.assertNotIn("expiry_passed", json.dumps(f))
        g = by_record(fetch_customer_facts(1042, ["subscription"], as_of="2026-10-05"))["subscriptions:3042"]
        self.assertIs(g["metadata"]["derived"]["expiry_passed"], True)
        self.assertEqual(g["metadata"]["status"], "Active")  # stored status never reinterpreted
        h = by_record(fetch_customer_facts(1042, ["subscription"], as_of="2026-10-01"))["subscriptions:3042"]
        self.assertIs(h["metadata"]["derived"]["expiry_passed"], False)

    def test_1042_latest_recharge(self):
        facts = fetch_customer_facts(1042, ["recharge"])
        first = facts[0]
        self.assertEqual(first["record_id"], "recharge_transactions:4254")
        self.assertEqual((first["metadata"]["amount"], first["metadata"]["status"]), ("399.00", "SUCCESS"))
        self.assertEqual(first["metadata"]["timestamp"], "2026-04-17 11:06:00")
        self.assertLessEqual(len(facts), 3)

    def test_1042_tickets(self):
        facts = fetch_customer_facts(1042, ["tickets"])
        self.assertEqual({f["record_id"] for f in facts},
                         {"tickets:12099", "tickets:12323", "tickets:11335"})
        self.assertEqual(set(facts[0]["metadata"]["status_vocabulary"]), {"Open", "InProgress", "Closed"})

    def test_1056_latest_recharge_failed(self):
        first = fetch_customer_facts(1056, ["recharge"])[0]
        self.assertEqual(first["record_id"], "recharge_transactions:4996")
        self.assertEqual((first["metadata"]["amount"], first["metadata"]["status"]), ("949.00", "FAILED"))

    def test_1829_invoice_ledger_mismatch(self):
        f = by_record(fetch_customer_facts(1829, ["invoice"]))["invoices:6740"]
        md = f["metadata"]
        self.assertEqual((md["total_amount"], md["payment_status"]), ("581.65", "Unpaid"))
        pay = {p["transaction_id"]: p for p in md["payments"]}
        self.assertEqual((pay["7976"]["amount"], pay["7976"]["status"]), ("581.65", "SUCCESS"))
        self.assertEqual(md["success_payments_sum"], 581.65)
        self.assertIs(md["derived"]["status_ledger_mismatch"], True)
        self.assertEqual(md["payment_status"], "Unpaid")  # stored value untouched

    def test_no_mismatch_flag_on_a_paid_invoice(self):
        facts = fetch_customer_facts(1829, ["invoice"], limit=6)
        paid = [f for f in facts if f["metadata"]["payment_status"] == "Paid"]
        self.assertTrue(paid)
        self.assertTrue(all("derived" not in f["metadata"] for f in paid))

    def test_1015_has_no_tickets(self):
        self.assertEqual(fetch_customer_facts(1015, ["tickets"]), [])

    def test_unknown_customer_and_none_return_empty(self):
        self.assertEqual(fetch_customer_facts(99999999, list(INTENTS)), [])
        self.assertEqual(fetch_customer_facts(None, list(INTENTS)), [])

    def test_unknown_intent_is_rejected(self):
        with self.assertRaises(ValueError):
            fetch_customer_facts(1042, ["balance_transfer"])

    def test_schema_and_concept(self):
        for f in fetch_customer_facts(1042, list(INTENTS)):
            self.assertEqual(f["source"], "structured_sql")
            self.assertEqual(f["retrieval_method"], "structured_sql")
            self.assertTrue(re.fullmatch(r"[a-z_]+:[A-Za-z0-9_]+", f["record_id"]), f["record_id"])
            self.assertEqual(f["record_id"].split(":")[0], f["dataset"])
            self.assertTrue(f["metadata"]["concept"], f["record_id"])
        recharge = fetch_customer_facts(1042, ["recharge"])[0]
        self.assertEqual(recharge["metadata"]["concept"], "Recharge")
        self.assertEqual(recharge["category"], "C03")  # structured category_tag, passed through untouched


class TestIsolation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = open_readonly()
        pick = ("SELECT customer_id FROM customer_master WHERE account_type = ? "
                "ORDER BY (CAST(customer_id AS INTEGER) * 7919) % 1009 LIMIT ?")
        cls.customers = ([r[0] for r in cls.db.execute(pick, ("Prepaid", 13))]
                         + [r[0] for r in cls.db.execute(pick, ("Postpaid", 12))])

    def owner_of(self, fact):
        table, pk = fact["dataset"], fact["record_id"].split(":", 1)[1]
        if table == "customer_master":
            return pk
        if table == "recharge_transactions":
            row = self.db.execute("SELECT c.customer_id FROM recharge_transactions r JOIN customer_master c "
                                  "ON c.msisdn = r.msisdn WHERE r.recharge_id = ?", (pk,)).fetchone()
            return row[0]
        if table == "kyc_records" and pk == "none":
            return str(fact["metadata"]["customer_id"])  # marker: no row exists to own
        owner_sql = {
            "kyc_records": "SELECT customer_id FROM kyc_records WHERE kyc_id = ?",
            "subscriptions": "SELECT customer_id FROM subscriptions WHERE subscription_id = ?",
            "tickets": "SELECT customer_id FROM tickets WHERE ticket_id = ?",
            "invoices": "SELECT customer_id FROM invoices WHERE invoice_id = ?",
        }[table]
        return self.db.execute(owner_sql, (pk,)).fetchone()[0]

    def test_zero_leakage_25_customers_all_intents(self):
        self.assertEqual(len(self.customers), 25)
        accounts = {r[0] for r in self.db.execute(
            "SELECT account_type FROM customer_master WHERE customer_id IN (%s)" %
            ",".join("?" * 25), self.customers)}
        self.assertEqual(accounts, {"Prepaid", "Postpaid"})
        leaks, checked = [], 0
        for cid in self.customers:
            for intent in INTENTS:
                for fact in fetch_customer_facts(cid, [intent], limit=5):
                    checked += 1
                    if str(self.owner_of(fact)) != str(cid) or fact["metadata"]["customer_id"] != int(cid):
                        leaks.append((cid, intent, fact["record_id"]))
                    for p in fact["metadata"].get("payments", []):
                        owner = self.db.execute("SELECT customer_id FROM payment_transactions "
                                                "WHERE transaction_id = ?", (p["transaction_id"],)).fetchone()[0]
                        if str(owner) != str(cid):
                            leaks.append((cid, intent, "payment:" + p["transaction_id"]))
        print(f"\nisolation: {len(self.customers)} customers x {len(INTENTS)} intents, "
              f"{checked} facts checked, leakage={len(leaks)}")
        self.assertGreater(checked, 100)
        self.assertEqual(leaks, [])

    def test_allow_list_and_msisdn_masking(self):
        for cid in self.customers:
            msisdn = self.db.execute("SELECT msisdn FROM customer_master WHERE customer_id = ?",
                                     (cid,)).fetchone()[0]
            for fact in fetch_customer_facts(cid, list(INTENTS), limit=5):
                self.assertFalse(FORBIDDEN_KEYS & set(walk_keys(fact)), fact["record_id"])
                self.assertNotIn(msisdn, json.dumps(fact), f"full msisdn leaked in {fact['record_id']}")
        recharge = fetch_customer_facts(1042, ["recharge"])[0]
        self.assertIn("****4714", recharge["content"])


class TestReadOnlyAndSqlHygiene(unittest.TestCase):

    def test_write_attempts_raise(self):
        conn = open_readonly()
        for stmt in ("UPDATE customer_master SET kyc_status = 'Complete' WHERE customer_id = '1042'",
                     "DELETE FROM tickets WHERE ticket_id = '12099'",
                     "CREATE TABLE should_not_exist (x)"):
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute(stmt)
        conn.close()

    def test_database_unchanged(self):
        row = open_readonly().execute("SELECT kyc_status FROM customer_master WHERE customer_id = '1042'").fetchone()
        self.assertEqual(row[0], "Pending")

    def test_no_fstring_sql_in_hybrid(self):
        findings = []
        pattern = re.compile(r"""\.(?:execute|executemany|executescript)\(\s*f["']""")
        for path in sorted(HYBRID_DIR.glob("*.py")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    findings.append(f"{path.name}:{n}: {line.strip()}")
        self.assertEqual(findings, [], "SQL must be parameterised, not formatted")


class TestNoCategoryJoin(unittest.TestCase):

    def test_no_module_compares_category_codes(self):
        """Category C-codes conflict across branches; hybrid/ code must never compare or join on them."""
        patterns = [
            re.compile(r"""category["']?\]?\)?\s*(?:==|!=|\bin\b|\bnot in\b)"""),
            re.compile(r"""(?:==|!=)\s*[\w\.\["']*category"""),
            re.compile(r"""\bcategory_tag\b[^\n]*(?:==|!=)"""),
            re.compile(r"""(?:groupby|group_by|merge|join)\([^)\n]*category"""),
        ]
        findings = []
        for path in sorted(HYBRID_DIR.glob("*.py")):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                if any(p.search(line) for p in patterns):
                    findings.append(f"{path.name}:{n}: {line.strip()}")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
