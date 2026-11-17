"""
Tests for StructuredRetriever.customer_scoped_filter: customer-scoped lookups on tables that are keyed by
msisdn (cdr, recharge_transactions, sim_inventory) or have no customer key at all (offers, plan_master, ...).
"""

import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from query_parser import parse_query
from retriever import StructuredRetriever

DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed", "structured",
                                  "novatel_structured.db"))


def msisdn_of(db, customer_id):
    return db.execute("SELECT msisdn FROM customer_master WHERE customer_id = ?", (str(customer_id),)).fetchone()[0]


class TestCustomerScoping(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = StructuredRetriever()
        cls.db = sqlite3.connect(f"file:{DB.replace(os.sep, '/')}?mode=ro", uri=True)

    def test_recharge_transactions_for_1056_are_that_customers_msisdn_rows(self):
        out = self.r.search("Show recharge transactions for customer 1056", top_k=50)
        own = msisdn_of(self.db, 1056)
        self.assertEqual(out["parsed_query"]["table"], "recharge_transactions")
        self.assertTrue(out["results"])
        self.assertTrue(all(x["metadata"]["msisdn"] == own for x in out["results"]))
        self.assertTrue(all(x["metadata"]["route"] == "msisdn_mapping" for x in out["results"]))
        self.assertTrue(out["executed"])
        self.assertEqual(out["route"], "msisdn_mapping")
        expected = self.db.execute("SELECT count(*) FROM recharge_transactions WHERE msisdn = ?", (own,)).fetchone()[0]
        self.assertEqual(len(out["results"]), min(expected, 50))

    def test_cdr_and_sim_inventory_likewise(self):
        for table in ("cdr", "sim_inventory"):
            found = False
            for cid in range(1001, 1200):
                out = self.r.customer_scoped_filter(table, cid, top_k=500)
                own = msisdn_of(self.db, cid)
                if out["results"]:
                    found = True
                    self.assertTrue(all(x["metadata"]["msisdn"] == own for x in out["results"]), (table, cid))
                    self.assertEqual(out["route"], "msisdn_mapping")
                    break
            self.assertTrue(found, f"no customer with {table} rows among the first 200")

    def test_tables_with_customer_id_are_unchanged(self):
        out = self.r.customer_scoped_filter("tickets", 1042)
        self.assertEqual({x["record_id"] for x in out["results"]}, {"12099", "12323", "11335"})
        self.assertNotIn("route", out)
        self.assertTrue(all("route" not in x["metadata"] for x in out["results"]))

    def test_tables_without_a_customer_key_return_empty_with_a_note(self):
        for table in ("offers", "plan_master", "network_sites"):
            out = self.r.customer_scoped_filter(table, 1042)
            self.assertEqual(out["results"], [], table)
            self.assertIs(out["executed"], False, table)
            self.assertEqual(out["note"], "table has no customer key; cannot scope to a customer", table)

    def test_unknown_customer_returns_empty(self):
        out = self.r.customer_scoped_filter("recharge_transactions", 99999999)
        self.assertEqual(out["results"], [])
        self.assertIn("unknown customer", out["note"])

    def test_unknown_table_is_never_queried(self):
        out = self.r.customer_scoped_filter("sqlite_master; DROP TABLE tickets", 1042)
        self.assertEqual(out["results"], [])
        self.assertIs(out["executed"], False)
        self.assertEqual(self.db.execute("SELECT count(*) FROM tickets").fetchone()[0] > 0, True)

    def test_injection_strings_return_empty(self):
        for evil in ("1001' OR '1'='1", "1001; DROP TABLE customer_master", "' OR 1=1 --", "1001 OR 1=1"):
            for table in ("recharge_transactions", "cdr", "tickets", "invoices"):
                out = self.r.customer_scoped_filter(table, evil, top_k=500)
                self.assertEqual(out["results"], [], (table, evil))
        self.assertGreater(self.db.execute("SELECT count(*) FROM customer_master").fetchone()[0], 1000)

    def test_exact_filter_on_customer_id_is_routed_through_scoping(self):
        out = self.r.exact_filter("recharge_transactions", "customer_id", 1056, top_k=5)
        own = msisdn_of(self.db, 1056)
        self.assertTrue(out["results"])
        self.assertTrue(all(x["metadata"]["msisdn"] == own for x in out["results"]))

    def test_no_such_column_is_never_raised_for_any_table(self):
        from schema import list_tables
        for table in list_tables():
            out = self.r.customer_scoped_filter(table, 1042, top_k=3)
            self.assertIn("results", out, table)

    def test_200_sampled_customers_every_row_belongs_to_that_customer(self):
        ids = [r[0] for r in self.db.execute(
            "SELECT customer_id FROM customer_master ORDER BY (CAST(customer_id AS INTEGER) * 7919) % 1013 LIMIT 200")]
        self.assertEqual(len(ids), 200)
        checked = 0
        for cid in ids:
            for table in ("recharge_transactions", "cdr", "sim_inventory", "tickets", "invoices", "subscriptions"):
                out = self.r.customer_scoped_filter(table, cid, top_k=100)
                for x in out["results"]:
                    row = x["metadata"]
                    if table in ("recharge_transactions", "cdr", "sim_inventory"):
                        owner = self.db.execute(
                            "SELECT c.customer_id FROM customer_master c WHERE c.msisdn = ?", (row["msisdn"],)).fetchone()[0]
                    else:
                        owner = row["customer_id"]
                    self.assertEqual(str(owner), str(cid), (table, cid, x["record_id"]))
                    checked += 1
        print(f"\nscoping: 200 customers x 6 tables, {checked} rows checked, 0 foreign rows")
        self.assertGreater(checked, 500)

    def test_search_path_end_to_end_for_msisdn_table(self):
        parsed = parse_query("Show recharge transactions for customer 1056")
        self.assertEqual((parsed["table"], parsed["filter_column"]), ("recharge_transactions", "customer_id"))


class TestEmptyReasonContract(unittest.TestCase):
    """customer_scoped_filter returns a string key "empty_reason" on EVERY return:
        unknown table                                    -> "unknown_table"      (executed=False)
        table has no customer key                        -> "table_not_scopable" (executed=False)
        msisdn path, customer not found                  -> "unknown_customer"   (executed=True)
        customer_id or msisdn path with zero rows        -> "no_rows"            (executed=True)
        rows returned                                    -> None
    executed, route, note text and result rows are exactly as before."""

    REASONS = {"unknown_table", "table_not_scopable", "unknown_customer", "no_rows", None}

    @classmethod
    def setUpClass(cls):
        cls.r = StructuredRetriever()
        cls.db = sqlite3.connect(f"file:{DB.replace(os.sep, '/')}?mode=ro", uri=True)

    def keys(self, out):
        return set(out)

    def test_unknown_table(self):
        out = self.r.customer_scoped_filter("no_such_table", 1042)
        self.assertEqual(out["empty_reason"], "unknown_table")
        self.assertIs(out["executed"], False)
        self.assertEqual(out["results"], [])
        self.assertEqual(out["note"], "unknown table 'no_such_table'; cannot scope to a customer")
        self.assertEqual(self.keys(out), {"results", "latency_sec", "executed", "note", "empty_reason"})

    def test_table_not_scopable(self):
        for table in ("offers", "plan_master", "network_sites"):
            out = self.r.customer_scoped_filter(table, 1042)
            self.assertEqual(out["empty_reason"], "table_not_scopable", table)
            self.assertIs(out["executed"], False, table)
            self.assertEqual(out["note"], "table has no customer key; cannot scope to a customer", table)
            self.assertEqual(self.keys(out), {"results", "latency_sec", "executed", "note", "empty_reason"}, table)

    def test_unknown_customer_on_the_msisdn_path(self):
        for table in ("recharge_transactions", "cdr", "sim_inventory"):
            out = self.r.customer_scoped_filter(table, 99999999)
            self.assertEqual(out["empty_reason"], "unknown_customer", table)
            self.assertIs(out["executed"], True, table)
            self.assertEqual(out["results"], [], table)
            self.assertEqual(out["note"], "unknown customer; nothing to scope to", table)
            self.assertEqual(self.keys(out), {"results", "latency_sec", "executed", "note", "empty_reason"}, table)

    def test_known_customer_with_zero_rows_on_the_msisdn_path_is_no_rows(self):
        own = msisdn_of(self.db, 1004)
        self.assertEqual(self.db.execute("SELECT count(*) FROM recharge_transactions WHERE msisdn = ?", (own,)).fetchone()[0], 0)
        out = self.r.customer_scoped_filter("recharge_transactions", 1004)
        self.assertEqual(out["empty_reason"], "no_rows")
        self.assertIs(out["executed"], True)
        self.assertEqual(out["results"], [])
        self.assertEqual(out["route"], "msisdn_mapping")
        self.assertNotIn("note", out)
        self.assertEqual(self.keys(out), {"results", "latency_sec", "executed", "route", "empty_reason"})

    def test_zero_rows_on_the_customer_id_path_is_no_rows(self):
        self.assertEqual(self.db.execute("SELECT count(*) FROM tickets WHERE customer_id = ?", ("1001",)).fetchone()[0], 0)
        for cid in (1001, 99999999):                                   # a customer without tickets, and an id that does not exist
            out = self.r.customer_scoped_filter("tickets", cid)
            self.assertEqual(out["empty_reason"], "no_rows", cid)
            self.assertIs(out["executed"], True, cid)
            self.assertEqual(out["results"], [], cid)
            self.assertNotIn("route", out)
            self.assertNotIn("note", out)
            self.assertEqual(self.keys(out), {"results", "latency_sec", "executed", "empty_reason"}, cid)

    def test_rows_returned_means_empty_reason_none_and_the_rows_are_unchanged(self):
        out = self.r.customer_scoped_filter("tickets", 1042)
        self.assertIsNone(out["empty_reason"])
        self.assertIn("empty_reason", out)
        self.assertEqual({x["record_id"] for x in out["results"]}, {"12099", "12323", "11335"})
        self.assertEqual(out["results"], self.r._plain_filter("tickets", "customer_id", 1042, 10)["results"])
        self.assertEqual(self.keys(out), {"results", "latency_sec", "executed", "empty_reason"})
        own = msisdn_of(self.db, 1056)
        out = self.r.customer_scoped_filter("recharge_transactions", 1056, top_k=50)
        self.assertIsNone(out["empty_reason"])
        self.assertEqual(out["route"], "msisdn_mapping")
        self.assertTrue(all(x["metadata"]["msisdn"] == own and x["metadata"]["route"] == "msisdn_mapping" for x in out["results"]))
        self.assertEqual(self.keys(out), {"results", "latency_sec", "executed", "route", "empty_reason"})

    def test_exact_filter_on_customer_id_carries_the_key_through(self):
        self.assertIsNone(self.r.exact_filter("tickets", "customer_id", 1042)["empty_reason"])
        self.assertEqual(self.r.exact_filter("tickets", "customer_id", 1001)["empty_reason"], "no_rows")

    def test_contract_over_every_table_and_a_sample_of_customers(self):
        from schema import list_tables
        seen = set()
        for table in list_tables():
            for cid in (1001, 1004, 1042, 1056, 99999999):
                out = self.r.customer_scoped_filter(table, cid, top_k=5)
                reason = out["empty_reason"]
                seen.add(reason)
                self.assertIn(reason, self.REASONS, (table, cid))
                self.assertEqual(bool(out["results"]), reason is None, (table, cid))              # rows <=> None
                self.assertEqual(out["executed"] is False, reason in ("unknown_table", "table_not_scopable"), (table, cid))
        self.assertEqual(seen, {None, "table_not_scopable", "unknown_customer", "no_rows"})        # every reachable value was exercised

    def test_the_docstring_lists_the_contract(self):
        doc = StructuredRetriever.customer_scoped_filter.__doc__
        for value in ("empty_reason", "unknown_table", "table_not_scopable", "unknown_customer", "no_rows"):
            self.assertIn(value, doc)


if __name__ == "__main__":
    unittest.main(verbosity=2)
