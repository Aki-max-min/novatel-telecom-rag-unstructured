"""
Structured-parser trial (NO LLM): run the rule-based structured side on a fixed question list and record what it does.

    python -m integration.eval.parser_trial run --label before_integrate     # on branch integrate/kg-ontology-router-ui
    python -m integration.eval.parser_trial run --label after_trial           # on branch trial/parser-wordboundary
    python -m integration.eval.parser_trial compare before_integrate after_trial

`run` writes data/experiments/parser_trial/<label>.json: for every question the parser decision (table, method, filter, error)
and the retrieval outcome (rows returned, first record ids, which lookup route ran), plus the git commit and the hash of
structured/query_parser.py so the parser version in use is on record.

Questions (all existing, none written for this trial):
  * structured/benchmark.json                                  15  (Person B's structured benchmark, with gold table / filter)
  * the 22 E14a questions (queryset.json)                      22  (8 database ones are the same questions as above; the 14
                                                                    document ones show what the parser does to document questions)
  * hybrid/benchmark/route_benchmark.json answerable items     14  (structured + 'both' items, session customer made explicit
                                                                    with the prefix "For customer <id>: ")
Duplicates (same question text) are run once.

`compare` classifies each difference and lists every regression. Definitions (stated, not hidden):
  gold questions (structured benchmark): parse is CORRECT if table, filter column and filter value equal the gold ones.
     regression = correct before, wrong after.  improvement = wrong before, correct after.
  document questions (E14a Q* / RW_*): the parser should return no database rows. Structured ROWS for a document question are a
     FALSE POSITIVE (an inference: the E14a failure analysis calls these noise). regression = no rows before, rows after;
     improvement = rows before, none after.
  route-benchmark questions (Person B's frozen benchmark, gold = the tables of expected_structured): "has gold evidence" means the
     parser chose a gold table AND returned rows. regression = had gold evidence before, none after;
     improvement = no gold evidence before, has it after; a change that neither gains nor loses gold evidence is reported as
     "changed, gold evidence unchanged" (for example a wrong table replaced by no table).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "experiments" / "parser_trial"
STRUCT_BENCH = ROOT / "structured" / "benchmark.json"
E14A = ROOT / "data" / "experiments" / "benchmark_base_vs_rag" / "queryset.json"
ROUTE_BENCH = ROOT / "hybrid" / "benchmark" / "route_benchmark.json"


def load_questions() -> list[dict]:
    qs: dict[str, dict] = {}
    for q in json.loads(STRUCT_BENCH.read_text(encoding="utf-8")):
        qs.setdefault(q["question"], {"id": q["id"], "kind": "structured_benchmark", "question": q["question"],
                                      "gold": {"table": q.get("expected_table"), "filter_column": q.get("expected_filter_column"),
                                               "filter_value": q.get("expected_filter_value")}})
    for q in json.loads(E14A.read_text(encoding="utf-8"))["queries"]:
        kind = "e14a_database" if q["reference_evidence"]["kind"] == "sql_record" else "e14a_document"
        qs.setdefault(q["question"], {"id": q["query_id"], "kind": kind, "question": q["question"], "gold": None})
    for q in json.loads(ROUTE_BENCH.read_text(encoding="utf-8"))["questions"]:
        if q["expected_outcome"] != "answer" or q["expected_route"] == "unstructured":
            continue
        text = q["question"] if not q.get("customer_id") else f"For customer {q['customer_id']}: {q['question']}"
        tables = sorted({f["table"] for f in q["expected_structured"] if f.get("table")})
        qs.setdefault(text, {"id": q["question_id"], "kind": "route_benchmark", "question": text,
                             "gold": {"tables": tables} if tables else None})
    return list(qs.values())


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout.strip()


def run(label: str) -> Path:
    sys.path.insert(0, str(ROOT / "structured"))
    from query_parser import parse_query
    from retriever import StructuredRetriever
    from integration.structured_guard import guarded_structured_search

    retriever = StructuredRetriever()
    rows = []
    try:
        for q in load_questions():
            parsed = parse_query(q["question"])
            g = guarded_structured_search(retriever, q["question"], 10)
            rows.append({**q, "table": parsed.get("table"), "method": parsed.get("method"),
                         "filter_column": parsed.get("filter_column"), "filter_value": parsed.get("filter_value"),
                         "parser_error": parsed.get("error"), "n_results": len(g.results),
                         "record_ids": [str(r["record_id"]) for r in g.results[:5]], "lookup_route": g.status["route"],
                         "executed": g.status["executed"]})
    finally:
        retriever.close()
    payload = {"label": label, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "git_commit": _git("rev-parse", "HEAD"),
               "git_branch": _git("branch", "--show-current"),
               "query_parser_blob_sha": _git("hash-object", "structured/query_parser.py"), "n_questions": len(rows), "rows": rows}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{label}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"{label}: {len(rows)} questions, parser blob {payload['query_parser_blob_sha'][:10]}, branch {payload['git_branch']} -> {path}")
    return path


def _parse_ok(row: dict) -> bool | None:
    gold = row.get("gold")
    if not gold or not gold.get("table"):
        return None
    return (row["table"] == gold["table"] and row["filter_column"] == gold["filter_column"]
            and str(row["filter_value"]) == str(gold["filter_value"]))


def compare(before_label: str, after_label: str) -> dict:
    b = json.loads((OUT_DIR / f"{before_label}.json").read_text(encoding="utf-8"))
    a = json.loads((OUT_DIR / f"{after_label}.json").read_text(encoding="utf-8"))
    after = {r["question"]: r for r in a["rows"]}
    gold_by_question = {q["question"]: q.get("gold") for q in load_questions()}
    changes, regressions, improvements = [], [], []
    for rb in b["rows"]:
        ra = after[rb["question"]]
        fields = ("table", "method", "filter_column", "filter_value", "parser_error", "n_results", "record_ids")
        diff = {f: [rb[f], ra[f]] for f in fields if rb[f] != ra[f]}
        if not diff:
            continue
        kind = rb["kind"]
        gold = gold_by_question.get(rb["question"])
        verdict = "changed (no gold)"
        if kind == "structured_benchmark":
            okb, oka = _parse_ok(rb), _parse_ok(ra)
            verdict = "regression" if okb and not oka else "improvement" if oka and not okb else "changed, parse correctness same"
            if okb is None:
                verdict = "changed (gold has no table)"
        elif kind == "e14a_document":
            verdict = ("regression: structured rows appear for a document question" if rb["n_results"] == 0 and ra["n_results"] > 0
                       else "improvement: false structured rows removed" if rb["n_results"] > 0 and ra["n_results"] == 0
                       else "changed, rows still returned" if ra["n_results"] > 0 else "changed, still no rows")
        elif kind == "route_benchmark" and gold and gold.get("tables"):
            has_b = rb["table"] in gold["tables"] and rb["n_results"] > 0
            has_a = ra["table"] in gold["tables"] and ra["n_results"] > 0
            verdict = ("regression: gold evidence lost" if has_b and not has_a
                       else "improvement: gold evidence gained" if has_a and not has_b else "changed, gold evidence unchanged")
        elif kind == "e14a_database":
            verdict = "changed (database question; see the gold check on the structured_benchmark row if present)"
        entry = {"id": rb["id"], "kind": kind, "question": rb["question"], "diff": diff, "verdict": verdict}
        changes.append(entry)
        (regressions if verdict.startswith("regression") else improvements if verdict.startswith("improvement") else []).append(entry)

    gold_rows_b = [r for r in b["rows"] if r["kind"] == "structured_benchmark"]
    summary = {"before": {k: b[k] for k in ("label", "git_branch", "git_commit", "query_parser_blob_sha")},
               "after": {k: a[k] for k in ("label", "git_branch", "git_commit", "query_parser_blob_sha")},
               "n_questions": len(b["rows"]), "n_changed": len(changes), "n_regressions": len(regressions), "n_improvements": len(improvements),
               "structured_benchmark_parse_correct": {"before": sum(bool(_parse_ok(r)) for r in gold_rows_b),
                                                      "after": sum(bool(_parse_ok(after[r["question"]])) for r in gold_rows_b),
                                                      "of": len(gold_rows_b)},
               "document_questions_returning_structured_rows": {
                   "before": sum(1 for r in b["rows"] if r["kind"] == "e14a_document" and r["n_results"] > 0),
                   "after": sum(1 for r in a["rows"] if r["kind"] == "e14a_document" and r["n_results"] > 0),
                   "of": sum(1 for r in b["rows"] if r["kind"] == "e14a_document")},
               "changes": changes}
    out = OUT_DIR / f"compare_{before_label}__{after_label}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--label", required=True)
    c = sub.add_parser("compare")
    c.add_argument("before")
    c.add_argument("after")
    args = ap.parse_args()
    if args.cmd == "run":
        run(args.label)
    else:
        s = compare(args.before, args.after)
        print(json.dumps({k: v for k, v in s.items() if k != "changes"}, indent=2))
        for ch in s["changes"]:
            print(f"- [{ch['verdict']}] {ch['id']} ({ch['kind']}): {ch['question'][:90]}")
            for f, (x, y) in ch["diff"].items():
                print(f"      {f}: {x!r} -> {y!r}")


if __name__ == "__main__":
    main()
