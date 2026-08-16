"""
Evaluator: runs benchmark.json through query_parser.py + retriever.py
and reports accuracy metrics for the structured retrieval branch.
"""

import json
import os
import time
from query_parser import parse_query
from retriever import StructuredRetriever

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BENCHMARK_PATH = os.path.join(SCRIPT_DIR, "benchmark.json")


def load_benchmark(path=BENCHMARK_PATH):
    with open(path, "r") as f:
        return json.load(f)


def evaluate_parsing(benchmark):
    """
    Checks whether parse_query() correctly identifies table/method/filter
    for every benchmark question. This tests the query understanding layer.
    """
    results = []

    for item in benchmark:
        question = item["question"]
        parsed = parse_query(question)

        is_negative_case = item.get("query_type") == "negative"

        if is_negative_case:
            # For negative cases, success = correctly failing to resolve
            passed = parsed.get("table") is None or parsed.get("method") in (None, "exact_filter_unresolved")
        else:
            table_match = parsed.get("table") == item.get("expected_table")
            method_match = parsed.get("method") == item.get("expected_method")
            filter_col_match = parsed.get("filter_column") == item.get("expected_filter_column")
            filter_val_match = str(parsed.get("filter_value")) == str(item.get("expected_filter_value"))
            passed = table_match and method_match and filter_col_match and filter_val_match

        results.append({
            "id": item["id"],
            "question": question,
            "query_type": item.get("query_type"),
            "passed": passed,
            "parsed": parsed,
            "expected": {
                "table": item.get("expected_table"),
                "method": item.get("expected_method"),
                "filter_column": item.get("expected_filter_column"),
                "filter_value": item.get("expected_filter_value"),
            }
        })

    return results


def evaluate_end_to_end(benchmark, retriever):
    """
    Runs each question through the full retriever.search() pipeline
    and measures latency + whether any results were returned (for non-negative cases).
    """
    results = []

    for item in benchmark:
        question = item["question"]
        is_negative_case = item.get("query_type") == "negative"

        start = time.time()
        res = retriever.search(question)
        latency = time.time() - start

        if is_negative_case:
            passed = len(res["results"]) == 0
        else:
            passed = len(res["results"]) > 0

        results.append({
            "id": item["id"],
            "question": question,
            "passed": passed,
            "num_results": len(res["results"]),
            "latency_sec": latency
        })

    return results


def print_report(parsing_results, e2e_results):
    print("=" * 70)
    print("STRUCTURED RETRIEVAL BENCHMARK REPORT")
    print("=" * 70)

    total = len(parsing_results)
    parsing_passed = sum(1 for r in parsing_results if r["passed"])
    e2e_passed = sum(1 for r in e2e_results if r["passed"])

    print(f"\nTotal benchmark questions: {total}")
    print(f"\n--- Query Parsing Accuracy ---")
    print(f"Passed: {parsing_passed}/{total} = {parsing_passed/total*100:.2f}%")

    print(f"\n--- End-to-End Retrieval Accuracy ---")
    print(f"Passed: {e2e_passed}/{total} = {e2e_passed/total*100:.2f}%")

    avg_latency = sum(r["latency_sec"] for r in e2e_results) / total
    print(f"\nAverage latency: {avg_latency*1000:.2f} ms")

    print(f"\n--- Failures (Parsing) ---")
    failures = [r for r in parsing_results if not r["passed"]]
    if not failures:
        print("None. All parsing tests passed.")
    else:
        for f in failures:
            print(f"\n[{f['id']}] {f['question']}")
            print(f"  Expected: {f['expected']}")
            print(f"  Got:      {f['parsed']}")

    print(f"\n--- Failures (End-to-End) ---")
    e2e_failures = [r for r in e2e_results if not r["passed"]]
    if not e2e_failures:
        print("None. All end-to-end tests passed.")
    else:
        for f in e2e_failures:
            print(f"[{f['id']}] {f['question']} -- num_results={f['num_results']}")

    print("\n" + "=" * 70)

    # Save results as an artifact, matching the unstructured branch's convention
    report = {
        "total_questions": total,
        "parsing_accuracy": parsing_passed / total,
        "end_to_end_accuracy": e2e_passed / total,
        "average_latency_sec": avg_latency,
        "parsing_results": parsing_results,
        "end_to_end_results": e2e_results
    }
    report_path = os.path.join(SCRIPT_DIR, "structured_retrieval_evaluation.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nFull report saved to: {report_path}")


if __name__ == "__main__":
    benchmark = load_benchmark()
    retriever = StructuredRetriever()

    parsing_results = evaluate_parsing(benchmark)
    e2e_results = evaluate_end_to_end(benchmark, retriever)

    print_report(parsing_results, e2e_results)

    retriever.close()