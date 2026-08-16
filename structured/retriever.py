"""
StructuredRetriever: the main retrieval engine for the structured branch.
Outputs results in the Common Result Schema so they can be combined
with the unstructured (FAISS) branch's results.
"""

import time
from data_loader import DataLoader
from normalizer import normalize_row
from schema import get_schema, list_tables


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

    def exact_filter(self, table_name, column, value, top_k=10):
        """Retrieval method: exact_filter -- find records matching a column value."""
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