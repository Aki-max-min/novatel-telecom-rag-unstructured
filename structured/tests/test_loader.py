"""
Unit tests for data_loader.py -- confirms all 28 tables load correctly
with expected row counts and that exact lookup / filter functions work.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
from data_loader import DataLoader
from schema import list_tables


# Expected row counts, locked in from the verified build (Step 1 validation)
EXPECTED_ROW_COUNTS = {
    "customer_master": 1809, "plan_master": 25, "subscriptions": 1809,
    "recharge_transactions": 5259, "invoices": 3624, "payment_transactions": 4162,
    "sim_inventory": 964, "esim_profiles": 373, "network_sites": 151,
    "network_alarms": 3049, "tickets": 1486, "cdr": 16017, "roaming_usage": 544,
    "kyc_records": 870, "porting_requests": 223, "orders": 786,
    "corporate_accounts": 174, "device_config": 77, "device_registry": 507,
    "retail_outlets": 93, "technicians": 22, "ott_subscriptions": 576,
    "offers": 21, "fraud_cases": 174, "vas_subscriptions": 560,
    "coverage_5g": 26, "fiber_inventory": 262, "escalation_cases": 285,
}


class TestDataLoader(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.loader = DataLoader()

    @classmethod
    def tearDownClass(cls):
        cls.loader.close()

    def test_all_28_tables_registered(self):
        tables = list_tables()
        self.assertEqual(len(tables), 28, "Expected exactly 28 registered tables")

    def test_every_table_loads_without_error(self):
        for table in list_tables():
            with self.subTest(table=table):
                rows = self.loader.load_table(table, limit=5)
                self.assertIsInstance(rows, list)

    def test_row_counts_match_expected(self):
        for table, expected_count in EXPECTED_ROW_COUNTS.items():
            with self.subTest(table=table):
                actual_count = self.loader.row_count(table)
                self.assertEqual(
                    actual_count, expected_count,
                    f"{table}: expected {expected_count} rows, got {actual_count}"
                )

    def test_get_by_id_returns_correct_record(self):
        result = self.loader.get_by_id("customer_master", 1001)
        self.assertIsNotNone(result)
        self.assertEqual(result["customer_id"], "1001")  # stored as TEXT before normalization

    def test_get_by_id_returns_none_for_missing_id(self):
        result = self.loader.get_by_id("customer_master", 999999999)
        self.assertIsNone(result)

    def test_filter_by_returns_matching_rows(self):
        results = self.loader.filter_by("customer_master", "status", "Active")
        self.assertGreater(len(results), 0)
        for row in results:
            self.assertEqual(row["status"], "Active")

    def test_filter_by_returns_empty_for_no_match(self):
        results = self.loader.filter_by("customer_master", "status", "NonexistentStatus")
        self.assertEqual(results, [])

    def test_no_missing_primary_keys(self):
        """Every row in every table must have a non-null primary key."""
        from schema import get_schema
        for table in list_tables():
            with self.subTest(table=table):
                schema = get_schema(table)
                pk = schema["primary_key"]
                rows = self.loader.load_table(table)
                null_pks = [r for r in rows if r.get(pk) is None or r.get(pk) == ""]
                self.assertEqual(len(null_pks), 0, f"{table} has {len(null_pks)} rows with null PK")


if __name__ == "__main__":
    unittest.main(verbosity=2)