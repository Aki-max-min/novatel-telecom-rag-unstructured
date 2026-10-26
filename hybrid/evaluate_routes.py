"""
E13 Phase 7c - evaluation of the router + adapter + pipeline on the FROZEN route benchmark
(hybrid/benchmark/route_benchmark.json). Run ONCE, untuned; results go to
hybrid/benchmark/first_run_phase7.json and are committed before any further code change.

Metrics
  route accuracy        3-class (structured | unstructured | both), plus confusion matrix
  outcome accuracy      answer | needs_identity | refuse_other_customer
  structured fact recall  fraction of expected_structured items present among returned facts
                        (numeric strings compared numerically). Two expected shapes are matched
                        against the adapter's output explicitly:
                          * field "count_for_customer": satisfied when the adapter RAN the matching
                            intent (tickets -> tickets, kyc_records -> kyc) and returned exactly that
                            many real rows of that table (the kyc "no row" marker is not a row);
                          * field "sum_amount_success_for_invoice" (table payment_transactions): matched
                            to the adapter's invoices fact metadata["success_payments_sum"].
  leakage               any returned fact not owned by the session customer, checked independently
                        against the database (not via the adapter's own metadata)
  document hit@3/@5     any expected document id in the top-k of the full pipeline (real CrossEncoder)
  safety                needs_identity -> zero facts; refuse_other_customer -> zero facts/documents

Run from the repo root in the rag-api environment:
    python hybrid/evaluate_routes.py              # first run -> first_run_phase7.json (refuses to overwrite it)
    python hybrid/evaluate_routes.py --amended    # Phase 8c post-hoc run -> amended_run_phase8.json
    python hybrid/evaluate_routes.py --amended2   # Phase 8d post-hoc run -> amended2_run_phase8d.json
    python hybrid/evaluate_routes.py --amended3   # Phase 8e post-hoc run -> amended3_run_phase8e.json
Earlier result files are never overwritten.
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

from pipeline import run_hybrid_query  # noqa: E402
from structured_adapter import open_readonly  # noqa: E402

BENCH = Path(__file__).resolve().parent / "benchmark" / "route_benchmark.json"
OUT = Path(__file__).resolve().parent / "benchmark" / "first_run_phase7.json"
AMENDED_OUT = Path(__file__).resolve().parent / "benchmark" / "amended_run_phase8.json"
AMENDED2_OUT = Path(__file__).resolve().parent / "benchmark" / "amended2_run_phase8d.json"
AMENDED3_OUT = Path(__file__).resolve().parent / "benchmark" / "amended3_run_phase8e.json"
ROUTES = ["structured", "unstructured", "both"]
COUNT_INTENT = {"tickets": "tickets", "kyc_records": "kyc"}


def same(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def owner_of(db, fact):
    """Independent ownership check straight from the database."""
    table, pk = fact["dataset"], fact["record_id"].split(":", 1)[1]
    if table == "customer_master":
        return pk
    if table == "kyc_records" and pk == "none":
        return str(fact["metadata"]["customer_id"])
    if table == "recharge_transactions":
        row = db.execute("SELECT c.customer_id FROM recharge_transactions r JOIN customer_master c "
                         "ON c.msisdn = r.msisdn WHERE r.recharge_id = ?", (pk,)).fetchone()
        return row[0] if row else None
    sql = {"kyc_records": "SELECT customer_id FROM kyc_records WHERE kyc_id = ?",
           "subscriptions": "SELECT customer_id FROM subscriptions WHERE subscription_id = ?",
           "tickets": "SELECT customer_id FROM tickets WHERE ticket_id = ?",
           "invoices": "SELECT customer_id FROM invoices WHERE invoice_id = ?"}[table]
    row = db.execute(sql, (pk,)).fetchone()
    return row[0] if row else None


def match_expected(item, facts, intents_run):
    table, rid, field, value = item["table"], item["record_id"], item["field"], item["value"]
    if field == "count_for_customer":
        if COUNT_INTENT.get(table) not in intents_run:
            return False, "intent for this count was not run"
        real = [f for f in facts if f["dataset"] == table and f["metadata"].get("marker") is None]
        return len(real) == value, f"adapter returned {len(real)} real {table} rows"
    if field == "sum_amount_success_for_invoice":
        for f in facts:
            if f["record_id"] == f"invoices:{rid}":
                got = f["metadata"].get("success_payments_sum")
                return same(got, value), f"adapter success_payments_sum={got!r}"
        return False, f"no invoices:{rid} fact returned"
    for f in facts:
        if f["record_id"] == f"{table}:{rid}":
            got = f["metadata"].get(field)
            return same(got, value), f"adapter {field}={got!r}"
    return False, f"no {table}:{rid} fact returned"


def main():
    amended3 = "--amended3" in sys.argv[1:]
    amended2 = "--amended2" in sys.argv[1:]
    amended = "--amended" in sys.argv[1:] or amended2 or amended3
    out_path = (AMENDED3_OUT if amended3 else AMENDED2_OUT if amended2 else AMENDED_OUT if amended else OUT)
    if out_path.exists():
        raise SystemExit(f"{out_path.name} already exists: results files are never overwritten.")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    questions = json.loads(BENCH.read_text(encoding="utf-8"))["questions"]
    db = open_readonly()

    rows, misses = [], []
    leaks = []
    confusion = {e: Counter() for e in ROUTES}
    route_ok = outcome_ok = 0
    fact_found = fact_total = 0
    docs = {"unstructured": [0, 0, 0], "both": [0, 0, 0]}  # hit3, hit5, n
    safety = {}
    safety_docs = {}

    for item in questions:
        qid, cid = item["question_id"], item["customer_id"]
        out = run_hybrid_query(item["question"], cid)
        plan, facts, documents = out["route_plan"], out["facts"], out["documents"]
        intents_run = out["trace"]["intents_run"]

        r_ok = plan["route"] == item["expected_route"]
        o_ok = plan["outcome"] == item["expected_outcome"]
        route_ok += r_ok
        outcome_ok += o_ok
        confusion[item["expected_route"]][plan["route"]] += 1
        if not r_ok or not o_ok:
            misses.append({"question_id": qid, "kind": "route/outcome", "question": item["question"],
                           "expected": {"route": item["expected_route"], "outcome": item["expected_outcome"]},
                           "got": {"route": plan["route"], "outcome": plan["outcome"],
                                   "intents": plan["structured_intents"]},
                           "reason": plan["reasoning"]})

        for f in facts:
            if str(owner_of(db, f)) != str(cid):
                leaks.append({"question_id": qid, "record_id": f["record_id"], "session_customer": cid})

        found, details = 0, []
        for exp in item["expected_structured"]:
            ok, why = match_expected(exp, facts, intents_run)
            found += ok
            details.append({"expected": exp, "found": ok, "detail": why})
            if not ok:
                misses.append({"question_id": qid, "kind": "structured fact", "question": item["question"],
                               "expected": exp, "got": why,
                               "router": {"route": plan["route"], "intents": plan["structured_intents"]},
                               "reason": plan["reasoning"]})
        fact_found += found
        fact_total += len(item["expected_structured"])

        doc_ids = [d["metadata"]["document_id"] for d in documents]
        hit3 = hit5 = None
        if item["expected_document_ids"]:
            exp_docs = set(item["expected_document_ids"])
            hit3 = bool(exp_docs & set(doc_ids[:3]))
            hit5 = bool(exp_docs & set(doc_ids[:5]))
            bucket = docs[item["expected_route"]]
            bucket[0] += hit3
            bucket[1] += hit5
            bucket[2] += 1
            if not hit5 or not hit3:
                misses.append({"question_id": qid, "kind": "document hit@5" if not hit5 else "document hit@3",
                               "question": item["question"], "expected": sorted(exp_docs),
                               "got": {"top5": doc_ids[:5], "documents_ran": out["trace"]["documents_ran"]},
                               "reason": plan["reasoning"]})

        if item["expected_outcome"] != "answer":
            # facts must always be empty; documents must be empty only for refuse_other_customer
            # (needs_identity may return generic documents since Phase 8d)
            clean = not facts and (item["expected_outcome"] != "refuse_other_customer" or not documents)
            safety[item["expected_outcome"]] = bool(o_ok and clean)
            safety_docs[item["expected_outcome"]] = len(documents)
            if not (o_ok and clean):
                misses.append({"question_id": qid, "kind": "safety", "question": item["question"],
                               "expected": item["expected_outcome"], "got": plan["outcome"],
                               "facts_returned": [f["record_id"] for f in facts],
                               "documents_returned": doc_ids, "reason": plan["reasoning"]})

        rows.append({
            "question_id": qid, "question": item["question"], "customer_id": cid,
            "expected_route": item["expected_route"], "expected_outcome": item["expected_outcome"],
            "got_route": plan["route"], "got_outcome": plan["outcome"],
            "structured_intents": plan["structured_intents"], "has_policy_component": plan["has_policy_component"],
            "concept_hint": plan["concept_hint"], "graph_weight": plan["graph_weight"], "reasoning": plan["reasoning"],
            "facts_returned": [f["record_id"] for f in facts],
            "structured_expected": len(item["expected_structured"]), "structured_found": found,
            "structured_detail": details,
            "documents_top5": doc_ids[:5], "expected_document_ids": item["expected_document_ids"],
            "doc_hit@3": hit3, "doc_hit@5": hit5,
            "rerank_status": out["trace"].get("rerank_status"), "blocked": out["blocked"],
        })

    n = len(questions)
    matrix = [[confusion[e][g] for g in ROUTES] for e in ROUTES]
    summary = {
        "post_hoc": amended,
        "note": ("POST-HOC AMENDED RUN (" + ("Phase 8e, amended-3" if amended3 else "Phase 8d, amended-2" if amended2 else "Phase 8c") + "): made after "
                 "seeing earlier results of this frozen benchmark (first_run_phase7.json, commit bde1a4e"
                 + ("; amended_run_phase8.json, amended2_run_phase8d.json" if amended3 else "; amended_run_phase8.json" if amended2 else "") + "); gate/router fixes and the rerank "
                 "choice were motivated by what those runs showed. See docs/E13_phase8_posthoc_log.md.") if amended else
                "FIRST RUN, UNTUNED. Router/adapter were designed without reading this benchmark's file.",
        "questions": n,
        "route_accuracy": f"{route_ok}/{n}", "route_confusion_matrix": {"order": ROUTES, "rows_expected": matrix},
        "outcome_accuracy": f"{outcome_ok}/{n}",
        "structured_fact_recall": {"found": fact_found, "total": fact_total,
                                   "recall": round(fact_found / fact_total, 4) if fact_total else None},
        "leakage": len(leaks), "leaks": leaks,
        "document_hits": {k: {"hit@3": v[0], "hit@5": v[1], "n": v[2]} for k, v in docs.items()},
        "safety": safety,
        "safety_documents_returned": safety_docs,
        "miss_count": len(misses),
    }
    out_path.write_text(json.dumps({"post_hoc": amended, "summary": summary, "misses": misses,
                                    "per_question": rows},
                              indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")

    if leaks:
        print(f"!!! LEAKAGE DETECTED: {len(leaks)} fact(s) not owned by the session customer: {leaks}")
    print(("===== E13 PHASE 8e - frozen benchmark, AMENDED-3 RUN (post-hoc) =====" if amended3
           else "===== E13 PHASE 8d - frozen benchmark, AMENDED-2 RUN (post-hoc) =====" if amended2
           else "===== E13 PHASE 8c - frozen benchmark, AMENDED RUN (post-hoc) =====") if amended
          else "===== E13 PHASE 7 — frozen benchmark, FIRST RUN (untuned) =====")
    print(f"route accuracy: {route_ok}/{n}   confusion (rows expected, cols got; order {ROUTES}):")
    for e, row in zip(ROUTES, matrix):
        print(f"   {e:<13} {row}")
    print(f"outcome accuracy: {outcome_ok}/{n}")
    print(f"structured fact recall: {fact_found}/{fact_total} = {summary['structured_fact_recall']['recall']}    leakage: {len(leaks)}")
    u, b = docs["unstructured"], docs["both"]
    print(f"document hit@3 / hit@5 (unstructured items): {u[0]}/{u[2]} / {u[1]}/{u[2]}   (both items): {b[0]}/{b[2]} / {b[1]}/{b[2]}")
    print(f"safety documents returned: {safety_docs}")
    print(f"safety: needs_identity {'pass' if safety.get('needs_identity') else 'FAIL'}   "
          f"refuse_other_customer {'pass' if safety.get('refuse_other_customer') else 'FAIL'}")
    print(f"misses ({len(misses)}):")
    for m in misses:
        print(f"  [{m['question_id']}] {m['kind']}: expected={m['expected']} got={m['got']}")
        print(f"      q: {m['question']}")
        print(f"      reason: {m['reason']}")
    print(f"written to {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
