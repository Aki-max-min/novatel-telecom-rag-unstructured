"""
Phase 8e: clause decomposition trace for the 24 frozen route-benchmark questions plus the 29 main and 9 mini
questions -> hybrid/benchmark/clause_trace_phase8e.json. Also prints the main/mini questions whose gate
weight now differs from the Phase 5 weight (hybrid/evaluation_results.json).

No retrieval models are needed:  python hybrid/trace_clauses.py
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

from clauses import split_clauses, summarize  # noqa: E402
from query_gate import PERSONAL_FACT_TERMS, POSSESSIVE_NUMBER_TERMS, explain_gate  # noqa: E402
from router import route_query  # noqa: E402

OUT = Path(__file__).resolve().parent / "benchmark" / "clause_trace_phase8e.json"


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data["questions"]


def row(set_name, qid, question, customer_id):
    clauses = split_clauses(question, PERSONAL_FACT_TERMS, POSSESSIVE_NUMBER_TERMS)
    plan = route_query(question, customer_id)
    return {"set": set_name, "question_id": qid, "question": question, "customer_id": customer_id,
            "clauses": [{"text": c, "kind": k} for c, k in clauses],
            "personal": summarize(clauses)["personal"], "route": plan.route, "outcome": plan.outcome,
            "structured_intents": plan.structured_intents, "graph_weight": plan.graph_weight}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = []
    for item in load(REPO_ROOT / "hybrid" / "benchmark" / "route_benchmark.json"):
        rows.append(row("frozen_route_24", item["question_id"], item["question"], item["customer_id"]))
    main_q = load(REPO_ROOT / "ingestion" / "retrieval_benchmark.json")
    mini_q = load(REPO_ROOT / "knowledge_graph" / "graph_benchmark.json")
    for i, item in enumerate(main_q, 1):
        rows.append(row("main_29", item.get("question_id", f"main_{i:02d}"), item["question"], None))
    for i, item in enumerate(mini_q, 1):
        rows.append(row("mini_9", item.get("question_id", f"mini_{i:02d}"), item["question"], None))
    assert [sum(r["set"] == s for r in rows) for s in ("frozen_route_24", "main_29", "mini_9")] == [24, 29, 9]

    phase5 = json.loads((REPO_ROOT / "hybrid" / "evaluation_results.json").read_text(encoding="utf-8"))
    p5 = {q["question"]: q["graph_weight"] for run in phase5["runs"] for q in run["per_question"]}
    changed = []
    for r in rows:
        if r["set"] != "frozen_route_24":
            old, new = p5[r["question"]], explain_gate(r["question"])["graph_weight"]
            if old != new:
                changed.append({"set": r["set"], "question": r["question"], "phase5_weight": old, "now": new})

    OUT.write_text(json.dumps({"note": "Phase 8e clause decomposition; customer_id is None for main/mini (no session).",
                               "rows": rows, "gate_weight_changes_vs_phase5": changed},
                              indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"clause trace for {len(rows)} questions written to {OUT.relative_to(REPO_ROOT)}")
    print(f"main/mini questions whose gate weight differs from Phase 5: {len(changed)}")
    for c in changed:
        print(f"  [{c['set']}] {c['phase5_weight']} -> {c['now']} | {c['question']}")


if __name__ == "__main__":
    main()
