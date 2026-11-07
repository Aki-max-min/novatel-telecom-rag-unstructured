"""
StructuredRetriever: the main retrieval engine for the structured branch.
Outputs results in the Common Result Schema so they can be combined
with the unstructured (FAISS) branch's results.
"""

import re
import time
from data_loader import DataLoader
from normalizer import normalize_row
from schema import TABLE_SCHEMAS, get_schema, list_tables

# Foreign-key follow: parent table -> [(child table, child column)], derived from schema.py foreign_keys.
# Edges whose parent is customer_master or plan_master are excluded: those are the customer/plan lookups that the
# customer-scoped filters already cover, not "this record and its dependants" joins.
_NOT_A_PARENT = ("customer_master", "plan_master")
FK_CHILDREN = {}
for _child, _schema in TABLE_SCHEMAS.items():
    for _col, _parent in _schema.get("foreign_keys", {}).items():
        if _parent not in _NOT_A_PARENT:
            FK_CHILDREN.setdefault(_parent, []).append((_child, _col))

# "invoice 5001" / "ticket 11011": parent entity word -> parent table (only tables that appear as FK parents)
_PARENT_WORDS = {"invoice": "invoices", "ticket": "tickets", "site": "network_sites", "device": "device_config"}
_PARENT_ID = re.compile(r"\b(invoice|ticket|site|device)s?\s*#?\s*(?:id\s*)?[:=]?\s*(\d+)\b", re.IGNORECASE)
# words that name a child entity in the question (checked against tables other than the parent)
_CHILD_HINTS = {
    "payment_transactions": r"\bpayments?\b", "escalation_cases": r"\bescalat\w*", "network_alarms": r"\balarms?\b",
    "device_registry": r"\bregist\w*", "tickets": r"\b(?:tickets?|complaints?)\b", "invoices": r"\b(?:invoices?|bills?)\b",
    "subscriptions": r"\b(?:subscriptions?|plans?)\b", "recharge_transactions": r"\brecharges?\b",
    "kyc_records": r"\bkyc\b", "orders": r"\borders?\b", "fraud_cases": r"\bfraud\b",
}


class StructuredRetriever:
    def __init__(self, db_path=None):
        self.loader = DataLoader(db_path) if db_path else DataLoader()

    def _wrap_result(self, table_name, row_dict, retrieval_method, score=1.0):
        """Wrap a normalized row into the Common Result Schema."""
        schema = get_schema(table_name)
        pk = schema["primary_key"]
        category = schema.get("category_tag", "")

        # Build a human-readable content string summarizing the record
        content = self._build_content_string(table_name, row_dict)

        return {
            "source": "structured",
            "record_id": str(row_dict.get(pk)),
            "dataset": table_name,
            "category": category,
            "score": score,
            "retrieval_method": retrieval_method,
            "content": content,
            "metadata": row_dict
        }

    def _build_content_string(self, table_name, row_dict):
        """Generate a short natural-language-ish summary of the record."""
        parts = [f"{k}={v}" for k, v in row_dict.items() if v is not None]
        return f"{table_name} record: " + ", ".join(parts)

    def exact_lookup(self, table_name, id_value, top_k=1):
        """Retrieval method: exact_lookup -- find a record by its primary key."""
        start = time.time()
        raw_row = self.loader.get_by_id(table_name, id_value)
        latency = time.time() - start

        if raw_row is None:
            return {"results": [], "latency_sec": latency}

        normalized = normalize_row(table_name, raw_row)
        result = self._wrap_result(table_name, normalized, "exact_lookup", score=1.0)
        return {"results": [result], "latency_sec": latency}

    # --- customer scoping ------------------------------------------------------------------
    def _table_columns(self, table_name):
        """Column names of an allow-listed table (PRAGMA, cached). Unknown tables -> None (never queried)."""
        if get_schema(table_name) is None:   # allowlist = the tables registered in schema.py
            return None
        cache = self.__dict__.setdefault("_column_cache", {})
        if table_name not in cache:
            rows = self.loader.conn.execute("SELECT name FROM pragma_table_info(?)", (table_name,)).fetchall()
            cache[table_name] = [r[0] for r in rows]
        return cache[table_name]

    def customer_scoped_filter(self, table_name, customer_id, top_k=10):
        """All rows of `table_name` that belong to ONE customer, whatever the table's customer key is.

        * table has customer_id            -> filter on customer_id (unchanged behaviour)
        * else table has msisdn            -> look up the customer's OWN msisdn in customer_master (parameterised),
                                             and if exactly one row, filter the table on msisdn
                                             (result metadata route="msisdn_mapping"); unknown customer -> empty
        * neither (offers, plan_master, network_sites, ...) -> empty result with a note and executed=False
        Never raises "no such column", never returns unscoped rows, never falls back to an unfiltered query.
        Callers must pass the customer id of the SIGNED-IN session, not an id parsed from question text.
        """
        start = time.time()
        columns = self._table_columns(table_name)

        def empty(note, executed):
            return {"results": [], "latency_sec": time.time() - start, "executed": executed, "note": note}

        if columns is None:
            return empty(f"unknown table {table_name!r}; cannot scope to a customer", False)

        if "customer_id" in columns:
            res = self._plain_filter(table_name, "customer_id", customer_id, top_k)
            res["executed"] = True
            return res

        if "msisdn" in columns:
            rows = self.loader.conn.execute(
                "SELECT msisdn FROM customer_master WHERE customer_id = ?", (str(customer_id),)).fetchall()
            if len(rows) != 1 or not rows[0][0]:
                return empty("unknown customer; nothing to scope to", True)
            res = self._plain_filter(table_name, "msisdn", rows[0][0], top_k)
            for r in res["results"]:
                r["metadata"]["route"] = "msisdn_mapping"
            res["executed"] = True
            res["route"] = "msisdn_mapping"
            return res

        return empty("table has no customer key; cannot scope to a customer", False)

    def fk_follow(self, question, customer_id=None, top_k=20):
        """Parent record + its child rows through an allow-listed foreign key, or None if this is not such a question.

        Recognises "<invoice|ticket|site|device> <id>" together with a child entity word ("payment transactions",
        "escalation case", ...). The (parent, child, column) triple must be in FK_CHILDREN (taken from schema.py);
        table and column names are validated against the schema, values are parameterised, no free-form SQL.
        Customer scoping still applies: the parent's customer must equal `customer_id` (or the id written in the
        question when none is passed). Callers should pass the signed-in session's id. Every failure returns an
        empty result with a note - never the other customer's rows.
        Child rows carry metadata relation="fk:<parent table>.<column>".
        """
        match = _PARENT_ID.search(question or "")
        if not match:
            return None
        parent = _PARENT_WORDS[match.group(1).lower()]
        parent_id = match.group(2)
        hinted = [t for t, rx in _CHILD_HINTS.items() if t != parent and re.search(rx, question, re.IGNORECASE)]
        if not hinted:
            return None  # a plain "invoice 5001" lookup, not a join question

        start = time.time()

        def empty(note, executed, parsed=None):
            return {"results": [], "latency_sec": time.time() - start, "executed": executed, "note": note,
                    "parsed_query": parsed or {"method": "fk_follow", "table": parent, "record_id": parent_id}}

        edges = [(child, col) for child, col in FK_CHILDREN.get(parent, []) if child in hinted]
        if not edges:
            return empty(f"no foreign key from {parent} to {', '.join(hinted)}; cannot follow that relation", False)

        columns = self._table_columns(parent)
        if columns is None or "customer_id" not in columns:
            return empty(f"table {parent} has no customer key; cannot scope the join to a customer", False)
        if customer_id is None:
            from query_parser import extract_customer_id
            customer_id = extract_customer_id(question)
        if customer_id is None:
            return empty("a customer id is required to follow a record's foreign key", False)

        pk = get_schema(parent)["primary_key"]
        row = self.loader.conn.execute(
            f"SELECT * FROM {parent} WHERE {pk} = ?", (parent_id,)).fetchone()
        if row is None:
            return empty(f"{parent} record {parent_id} not found", True)
        parent_row = dict(row)
        if str(parent_row.get("customer_id")) != str(customer_id):
            return empty(f"{parent} record {parent_id} does not belong to the given customer", True)

        results = [self._wrap_result(parent, normalize_row(parent, parent_row), "fk_follow", score=1.0)]
        relation = None
        for child, col in edges:
            relation = f"fk:{parent}.{col}"
            child_columns = self._table_columns(child) or []
            sql = f"SELECT * FROM {child} WHERE {col} = ?"
            params = [parent_id]
            if "customer_id" in child_columns:   # extra safety: a child row must also carry the same customer
                sql += " AND customer_id = ?"
                params.append(str(customer_id))
            for child_row in self.loader.conn.execute(sql, params).fetchall()[:top_k]:
                result = self._wrap_result(child, normalize_row(child, dict(child_row)), "fk_follow", score=1.0)
                result["metadata"]["relation"] = relation
                results.append(result)
        note = None if len(results) > 1 else f"{parent} record {parent_id} has no child rows in {', '.join(c for c, _ in edges)}"
        out = {"results": results, "latency_sec": time.time() - start, "executed": True, "relation": relation,
               "parsed_query": {"method": "fk_follow", "table": parent, "record_id": parent_id, "children": [c for c, _ in edges]}}
        if note:
            out["note"] = note
        return out

    def _plain_filter(self, table_name, column, value, top_k):
        start = time.time()
        raw_rows = self.loader.filter_by(table_name, column, value)[:top_k]
        results = [self._wrap_result(table_name, normalize_row(table_name, r), "exact_filter", score=1.0)
                   for r in raw_rows]
        return {"results": results, "latency_sec": time.time() - start}

    def exact_filter(self, table_name, column, value, top_k=10):
        """Retrieval method: exact_filter -- find records matching a column value.
        A customer_id filter is always routed through customer_scoped_filter (see above)."""
        if column == "customer_id":
            return self.customer_scoped_filter(table_name, value, top_k=top_k)
        start = time.time()
        raw_rows = self.loader.filter_by(table_name, column, value)
        latency = time.time() - start

        raw_rows = raw_rows[:top_k]
        results = [
            self._wrap_result(table_name, normalize_row(table_name, r), "exact_filter", score=1.0)
            for r in raw_rows
        ]
        return {"results": results, "latency_sec": latency}

    def aggregate_count(self, table_name, column=None, value=None):
        """Retrieval method: aggregate -- count records, optionally filtered."""
        start = time.time()
        if column and value is not None:
            rows = self.loader.filter_by(table_name, column, value)
            count = len(rows)
        else:
            count = self.loader.row_count(table_name)
        latency = time.time() - start

        result = {
            "source": "structured",
            "record_id": None,
            "dataset": table_name,
            "category": get_schema(table_name).get("category_tag", ""),
            "score": 1.0,
            "retrieval_method": "aggregate",
            "content": f"Count of {table_name}" + (f" where {column}={value}" if column else "") + f" = {count}",
            "metadata": {"count": count, "filter_column": column, "filter_value": value}
        }
        return {"results": [result], "latency_sec": latency}

    def search(self, question, top_k=5):
        """
        Main entry point for natural-language queries.
        Parses the question, executes the right retrieval method,
        and returns Common Result Schema results.
        """
        from query_parser import parse_query

        fk = self.fk_follow(question, top_k=top_k)
        if fk is not None:
            return fk

        parsed = parse_query(question)

        if parsed.get("table") is None or parsed.get("method") in (None, "exact_filter_unresolved"):
            return {
                "results": [],
                "latency_sec": 0.0,
                "parsed_query": parsed,
                "note": "Query could not be confidently resolved to structured data. "
                        "May require unstructured/hybrid retrieval instead."
            }

        table = parsed["table"]
        method = parsed["method"]

        if method == "exact_filter" and parsed.get("filter_column") == "customer_id":
            res = self.exact_filter(table, "customer_id", parsed["filter_value"], top_k=top_k)

        elif method == "exact_filter":
            res = self.exact_filter(table, parsed["filter_column"], parsed["filter_value"], top_k=top_k)

        elif method == "aggregate":
            res = self.aggregate_count(table, parsed.get("filter_column"), parsed.get("filter_value"))

        else:
            res = {"results": [], "latency_sec": 0.0}

        res["parsed_query"] = parsed
        return res

    def close(self):
        self.loader.close()


if __name__ == "__main__":
    retriever = StructuredRetriever()

    print("=== Test 1: exact_lookup ===")
    res = retriever.exact_lookup("customer_master", 1001)
    print(f"Latency: {res['latency_sec']*1000:.2f} ms")
    for r in res["results"]:
        print(r)

    print("\n=== Test 2: exact_filter ===")
    res = retriever.exact_filter("invoices", "payment_status", "Overdue", top_k=3)
    print(f"Latency: {res['latency_sec']*1000:.2f} ms, found {len(res['results'])} results (showing top 3)")
    for r in res["results"]:
        print(r["record_id"], "-", r["content"][:100])

    print("\n=== Test 3: aggregate_count ===")
    res = retriever.aggregate_count("recharge_transactions", "status", "FAILED")
    print(f"Latency: {res['latency_sec']*1000:.2f} ms")
    print(res["results"][0]["content"])

    print("\n=== Test 4: end-to-end search() with natural language ===")
    test_qs = [
        "What plan is customer 1001 on?",
        "How many recharge_transactions have status FAILED?",
        "Is there a network outage?",
    ]
    for q in test_qs:
        res = retriever.search(q)
        print(f"\nQ: {q}")
        print(f"   Parsed: {res['parsed_query']}")
        print(f"   Results found: {len(res['results'])}")
        if res["results"]:
            print(f"   Top result: {res['results'][0]['content'][:100]}")
        if "note" in res:
            print(f"   Note: {res['note']}")

    retriever.close()