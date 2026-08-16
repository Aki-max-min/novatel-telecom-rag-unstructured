"""
Type normalization module. Converts raw TEXT values from SQLite
back into their correct Python types based on schema.py definitions.
"""

from datetime import datetime, date
from schema import get_schema


def normalize_value(value, field_type):
    """Convert a single raw string value into its correct Python type."""
    if value is None or value == "":
        return None

    try:
        if field_type == "integer":
            return int(value)

        elif field_type == "numeric":
            return float(value)

        elif field_type == "boolean":
            return str(value).strip().lower() in ("true", "1", "yes")

        elif field_type == "date":
            return datetime.strptime(value, "%Y-%m-%d").date()

        elif field_type == "datetime":
            # Handle both "YYYY-MM-DD HH:MM:SS" and plain date fallback
            try:
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return datetime.strptime(value, "%Y-%m-%d")

        else:
            # text, categorical -> return as-is (string)
            return value

    except (ValueError, TypeError):
        # If conversion fails, return the raw value rather than crashing
        return value


def normalize_row(table_name, row_dict):
    """Normalize every field in a single row (dict) according to its table schema."""
    schema = get_schema(table_name)
    if schema is None:
        raise ValueError(f"'{table_name}' is not a registered table.")

    normalized = {}
    for column, raw_value in row_dict.items():
        field_type = schema["columns"].get(column, "text")
        normalized[column] = normalize_value(raw_value, field_type)

    return normalized


def normalize_rows(table_name, rows):
    """Normalize a list of row dicts."""
    return [normalize_row(table_name, r) for r in rows]


if __name__ == "__main__":
    from data_loader import DataLoader

    loader = DataLoader()

    print("--- Test: normalize a customer_master row ---")
    raw_row = loader.load_table("customer_master", limit=1)[0]
    print("RAW:", raw_row)

    normalized = normalize_row("customer_master", raw_row)
    print("\nNORMALIZED:", normalized)
    print("\nType check:")
    for k, v in normalized.items():
        print(f"  {k}: {type(v).__name__} = {v}")

    print("\n--- Test: normalize an invoice row (numeric + date fields) ---")
    raw_invoice = loader.load_table("invoices", limit=1)[0]
    normalized_invoice = normalize_row("invoices", raw_invoice)
    print("total_amount type:", type(normalized_invoice["total_amount"]).__name__,
          "=", normalized_invoice["total_amount"])
    print("due_date type:", type(normalized_invoice["due_date"]).__name__,
          "=", normalized_invoice["due_date"])

    loader.close()