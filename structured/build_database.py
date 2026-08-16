import pandas as pd
import sqlite3
import os

CSV_FOLDER = "../data/raw/structured"
DB_PATH = "../data/processed/structured/novatel_structured.db"

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)

csv_files = [f for f in os.listdir(CSV_FOLDER) if f.endswith(".csv")]
print(f"Found {len(csv_files)} CSV files to load.\n")

for csv_file in csv_files:
    table_name = csv_file.replace(".csv", "")
    csv_path = os.path.join(CSV_FOLDER, csv_file)

    # KEY FIX: dtype=str forces pandas to read every column as text,
    # preventing overflow on large numeric-looking ID columns (e.g. iccid)
    df = pd.read_csv(csv_path, dtype=str)

    df.to_sql(table_name, conn, if_exists="replace", index=False)
    print(f"Loaded '{table_name}': {len(df)} rows, {len(df.columns)} columns")

conn.close()
print("\nDone. Database saved as:", DB_PATH)