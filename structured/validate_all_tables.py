import sqlite3
import os

# Build an absolute path to the database, relative to THIS script's location,
# not relative to whatever folder you happen to run the command from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "..", "data", "processed", "structured", "novatel_structured.db")
DB_PATH = os.path.normpath(DB_PATH)

print(f"Looking for database at: {DB_PATH}")

if not os.path.exists(DB_PATH):
    print("ERROR: Database file does not exist at that path. Did you run build_database.py first?")
    exit(1)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

print(f"\nTotal tables: {len(tables)}\n")

for t in tables:
    table_name = t[0]
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"{table_name}: {count} rows")

conn.close()