"""
Data loading module. Provides a single, schema-aware interface for
querying the NovaTel structured SQLite database.
"""

import sqlite3
import os
from schema import TABLE_SCHEMAS, list_tables, get_schema

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "data", "processed", "structured", "novatel_structured.db"))


class DataLoader:
    def __init__(self, db_path=DB_PATH):
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database not found at {db_path}. Run build_database.py first.")
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # lets us access columns by name

    def load_table(self, table_name, limit=None):
        """Load all rows from a table as a list of dicts."""
        if table_name not in TABLE_SCHEMAS:
            raise ValueError(f"'{table_name}' is not a registered table in schema.py")

        query = f"SELECT * FROM {table_name}"
        if limit:
            query += f" LIMIT {limit}"

        cursor = self.conn.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
        return rows

    def get_by_id(self, table_name, id_value):
        """Exact lookup by primary key."""
        schema = get_schema(table_name)
        if schema is None:
            raise ValueError(f"'{table_name}' is not a registered table.")
        pk = schema["primary_key"]

        cursor = self.conn.execute(f"SELECT * FROM {table_name} WHERE {pk} = ?", (str(id_value),))
        row = cursor.fetchone()
        return dict(row) if row else None

    def filter_by(self, table_name, column, value):
        """Exact filter on any single column."""
        if table_name not in TABLE_SCHEMAS:
            raise ValueError(f"'{table_name}' is not a registered table.")

        cursor = self.conn.execute(f"SELECT * FROM {table_name} WHERE {column} = ?", (str(value),))
        rows = [dict(row) for row in cursor.fetchall()]
        return rows

    def row_count(self, table_name):
        """Quick count check for validation."""
        cursor = self.conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
        return cursor.fetchone()["cnt"]

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    loader = DataLoader()
    print(f"Connected to database at: {DB_PATH}\n")

    print("Row counts per table:")
    total_rows = 0
    for table in list_tables():
        count = loader.row_count(table)
        total_rows += count
        print(f"  {table}: {count} rows")

    print(f"\nTotal rows across all 28 tables: {total_rows}")

    # Quick functional test: exact lookup
    print("\n--- Test: get_by_id ---")
    sample_customer = loader.load_table("customer_master", limit=1)[0]
    cid = sample_customer["customer_id"]
    result = loader.get_by_id("customer_master", cid)
    print(f"Looked up customer_id={cid}: {result['name'] if result else 'NOT FOUND'}")

    # Quick functional test: filter
    print("\n--- Test: filter_by ---")
    active_customers = loader.filter_by("customer_master", "status", "Active")
    print(f"Customers with status='Active': {len(active_customers)}")

    loader.close()