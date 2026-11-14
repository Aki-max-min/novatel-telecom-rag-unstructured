"""
System-level comparison on an EXISTING frozen benchmark (hybrid/benchmark/route_benchmark.json, Person B):
routed vs structured-only vs unstructured-only vs always-hybrid vs oracle-route.

    python -m integration.eval.evaluate_system --modes routed,structured,unstructured,hybrid,oracle --tag dev

Items used: the 22 answerable items (8 structured RB_S*, 8 unstructured RB_U*, 6 both RB_B*). The 2 safety items
(RB_X*, identity gating) belong to Person B's customer-scoped adapter and are NOT scored here (reported as excluded).
The benchmark phrases personal questions with a session customer ("my last recharge"). This system has no session,
so the customer is made explicit by prefixing "For customer <id>: " -- the ONLY change; ground truth is untouched.

Per item (all deterministic, no LLM judge):
    route_correct          final route == gold route (routed mode only is meaningful)
    structured_fact_hit    every scoreable expected_structured fact (table + row id + value text) appears in the
                           retrieved structured evidence
    document_hit           >= 1 expected document id appears in the retrieved document evidence
    answer_fact_recall     share of expected structured values that appear verbatim (numbers canonicalised) in the answer
    abstained              the system declined (should be False on all items)
    support                SUPPORTED / WEAK / UNSUPPORTED sentence counts (verifier = nli unless --verifier lexical)
Failure attribution (per item, first failing stage wins):
    router      final route != gold route
    retrieval   needed evidence (fact and/or document) not in the retrieved set
    generation  evidence present but the answer lacks the fact, abstained, or has unsupported sentences
    none        all of the above pass
Facts that cannot be scored by string match are skipped and counted: count_for_customer==0 (absence of rows) and
derived sums.
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from integration.qa.citations import numbers_in
from integration.qa.config import QAConfig
from integration.qa.system import answer_query

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "hybrid" / "benchmark" / "route_benchmark.json"
OUT_DIR = ROOT / "data" / "experiments" / "system_eval"
GOLD_ROUTE = {"structured": "structured", "unstructured": "unstructured", "both": "hybrid"}
SKIP_FIELDS = {"count_for_customer", "sum_amount_success_for_invoice"}


def load_items() -> tuple[list[dict], list[str]]:
    data = json.loads(BENCH.read_text(encoding="utf-8"))
    items, excluded = [], []
    for q in data["questions"]:
        if q["expected_outcome"] != "answer":
            excluded.append(q["question_id"])
            continue
        question = q["question"] if not q.get("customer_id") else f"For customer {q['customer_id']}: {q['question']}"
        items.append({**q, "system_question": question, "gold_route": GOLD_ROUTE[q["expected_route"]]})
    return items, excluded


def _scoreable(facts: list[dict]) -> list[dict]:
    return [f for f in facts if f["field"] not in SKIP_FIELDS]


def _value_in(text: str, value) -> bool:
    s = str(value)
    if s.lower() in text.lower():
        return True
    nums = numbers_in(s)
    return bool(nums) and nums <= numbers_in(text)


def fact_retrieved(fact: dict, evidence: list[dict]) -> bool:
    for e in evidence:
        if e.get("kind") != "table_row" or e.get("table") != fact["table"]:
            continue
        if fact["record_id"] is not None and str(e.get("row_id")) != str(fact["record_id"]):
            continue
        if _value_in(e["text"], fact["value"]):
            return True
    return False


def score_item(item: dict, res: dict) -> dict:
    evidence = res["evidence"]
    facts = _scoreable(item["expected_structured"])
    docs = item["expected_document_ids"]
    fact_hits = [fact_retrieved(f, evidence) for f in facts]
    doc_hit = any(e.get("document_id") in docs for e in evidence) if docs else None
    answer = res["answer_text"] or ""
    ans_hits = [_value_in(answer, f["value"]) for f in facts]
    counts = {"SUPPORTED": 0, "WEAK": 0, "UNSUPPORTED": 0}
    for s in res["sentences"]:
        counts[s["support_status"]] += 1

    final_route = res["route"].get("final_route")
    retrieval_ok = (all(fact_hits) if facts else True) and (doc_hit if docs else True)
    generation_ok = (not res["abstained"]) and (all(ans_hits) if facts else True) and counts["UNSUPPORTED"] == 0 \
        and bool(res["sentences"])
    if final_route != item["gold_route"]:
        failure = "router"
    elif not retrieval_ok:
        failure = "retrieval"
    elif not generation_ok:
        failure = "generation"
    else:
        failure = "none"
    return {
        "question_id": item["question_id"], "question": item["system_question"], "gold_route": item["gold_route"],
        "final_route": final_route, "router": res["router_name"], "router_label": res["route"].get("label"),
        "route_correct": final_route == item["gold_route"],
        "structured_fact_hit": (all(fact_hits) if facts else None), "n_facts_scored": len(facts),
        "n_facts_skipped": len(item["expected_structured"]) - len(facts),
        "document_hit": doc_hit,
        "answer_fact_recall": round(sum(ans_hits) / len(ans_hits), 3) if ans_hits else None,
        "abstained": res["abstained"], "support": counts, "failure": failure,
        "answer_text": answer, "error": res.get("error"), "total_ms": res["timings"].get("total_ms"),
        "evidence_ids": [(e["evidence_id"], e.get("table") or e.get("document_id"), e.get("row_id") or e.get("chunk_id")) for e in evidence],
    }


def aggregate(records: list[dict]) -> dict:
    def rate(pred, pool):
        pool = list(pool)
        return round(sum(1 for r in pool if pred(r)) / len(pool), 4) if pool else None

    struct = [r for r in records if r["structured_fact_hit"] is not None]
    docs = [r for r in records if r["document_hit"] is not None]
    recall = [r["answer_fact_recall"] for r in records if r["answer_fact_recall"] is not None]
    sentences = {k: sum(r["support"][k] for r in records) for k in ("SUPPORTED", "WEAK", "UNSUPPORTED")}
    total_s = sum(sentences.values())
    failures = {}
    for r in records:
        failures[r["failure"]] = failures.get(r["failure"], 0) + 1
    ms = sorted(r["total_ms"] for r in records if r["total_ms"])
    return {
        "n": len(records),
        "route_accuracy": rate(lambda r: r["route_correct"], records),
        "structured_fact_hit_rate": rate(lambda r: r["structured_fact_hit"], struct), "n_structured_items": len(struct),
        "document_hit_rate": rate(lambda r: r["document_hit"], docs), "n_document_items": len(docs),
        "answer_fact_recall_mean": round(sum(recall) / len(recall), 4) if recall else None,
        "abstention_rate": rate(lambda r: r["abstained"], records),
        "sentence_support": {**sentences, "supported_share": round(sentences["SUPPORTED"] / total_s, 4) if total_s else None,
                             "unsupported_share": round(sentences["UNSUPPORTED"] / total_s, 4) if total_s else None},
        "items_with_no_failure": failures.get("none", 0), "failure_attribution": failures,
        "median_total_ms": ms[len(ms) // 2] if ms else None,
        "by_gold_route": {g: {"n": sum(r["gold_route"] == g for r in records),
                              "route_accuracy": rate(lambda r: r["route_correct"], [x for x in records if x["gold_route"] == g]),
                              "no_failure": sum(1 for r in records if r["gold_route"] == g and r["failure"] == "none")}
                          for g in ("structured", "unstructured", "hybrid")},
    }


def run_mode(mode: str, items: list[dict], base_cfg: dict) -> dict:
    records = []
    for it in items:
        forced = {"routed": None, "structured": "structured", "unstructured": "unstructured", "hybrid": "hybrid",
                  "oracle": it["gold_route"]}[mode]
        cfg = QAConfig(**{**base_cfg, "forced_route": forced})
        res = answer_query(it["system_question"], cfg)
        records.append(score_item(it, res))
        print(f"  [{mode}] {it['question_id']} route={records[-1]['final_route']} gold={it['gold_route']} "
              f"fail={records[-1]['failure']}", flush=True)
    return {"mode": mode, "summary": aggregate(records), "records": records}


def hardware() -> dict:
    info = {"platform": platform.platform(), "python": platform.python_version()}
    try:
        import torch
        info["torch"] = torch.__version__
        info["cuda"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:  # noqa: BLE001
        pass
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="routed,structured,unstructured,hybrid,oracle")
    ap.add_argument("--router", default="auto")
    ap.add_argument("--verifier", default="nli", choices=["nli", "lexical"])
    ap.add_argument("--use-ontology", action="store_true")
    ap.add_argument("--use-doc-graph", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    items, excluded = load_items()
    if args.limit:
        items = items[:args.limit]
    base_cfg = {"router": args.router, "verifier": args.verifier, "use_ontology": args.use_ontology,
                "use_doc_graph": args.use_doc_graph}
    t0 = time.time()
    results = []
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        print(f"--> mode {mode}", flush=True)
        results.append(run_mode(mode, items, base_cfg))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"system_eval_{stamp}{('_' + args.tag) if args.tag else ''}.json"
    payload = {
        "experiment": "system-routed-vs-fixed", "timestamp_utc": stamp, "benchmark": str(BENCH.relative_to(ROOT)),
        "benchmark_version": json.loads(BENCH.read_text(encoding="utf-8")).get("version"),
        "n_items": len(items), "excluded_safety_items": excluded,
        "customer_made_explicit_by_prefix": "For customer <id>: ", "base_config": QAConfig(**base_cfg).as_dict(),
        "hardware": hardware(), "runtime_s": round(time.time() - t0, 1),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("\n| mode | route acc | struct fact hit | doc hit | answer fact recall | abstain | unsupported share | no failure | median ms |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        s = r["summary"]
        print(f"| {r['mode']} | {s['route_accuracy']} | {s['structured_fact_hit_rate']} | {s['document_hit_rate']} | "
              f"{s['answer_fact_recall_mean']} | {s['abstention_rate']} | {s['sentence_support']['unsupported_share']} | "
              f"{s['items_with_no_failure']}/{s['n']} | {s['median_total_ms']} |")
    print(f"\nsaved: {path}")


if __name__ == "__main__":
    main()
