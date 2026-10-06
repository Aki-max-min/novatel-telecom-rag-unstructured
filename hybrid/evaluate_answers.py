"""
E13 Phase 9c - deterministic evaluation of the answer layer on the FROZEN route benchmark.

ExtractiveAnswerer only; no LLM and no LLM judge. Run ONCE from the repo root in the rag-api environment:
    python hybrid/evaluate_answers.py            # first run -> answer_eval_phase9c.json (never overwritten)
    python hybrid/evaluate_answers.py --postfix  # post-hoc re-run after the Phase 9c fixes -> answer_eval_phase9c_postfix.json

Metrics (all deterministic):
  verifier pass rate     verify_answer ok on the answer (24/24 expected; any failure is a bug to report)
  citation validity      every cited id exists in the assembled context
  fact inclusion         fraction of expected_structured values that appear in the answer, numeric values
                         compared after normalisation; "count 0" items count as included when the answer
                         states there are none ("no tickets" / "no kyc_records row")
  safety                 needs_identity answer contains no account value (no [F#], none of the known account
                         values); refuse_other_customer answer cites nothing, does not contain the other
                         customer's number or any of that customer's data
"""

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

from answer import answer_question  # noqa: E402
from groundedness import numeric_tokens  # noqa: E402

BENCH = Path(__file__).resolve().parent / "benchmark" / "route_benchmark.json"
OUT = Path(__file__).resolve().parent / "benchmark" / "answer_eval_phase9c.json"
POSTFIX_OUT = Path(__file__).resolve().parent / "benchmark" / "answer_eval_phase9c_postfix.json"
SAMPLE_IDS = ["RB_S06", "RB_B01", "RB_B05", "RB_U02", "RB_X01", "RB_X02"]
# values of customers 1042 / 1056 that must never appear in an identity-less or refusal answer
ACCOUNT_VALUES = ["4254", "399.00", "4996", "949.00", "3042", "3056", "2026-10-03", "2025-09-22", "6740", "581.65",
                  "9146794714", "9756865116"]


def value_in_answer(item, answer):
    table, field, value = item["table"], item["field"], item["value"]
    if field == "count_for_customer":
        if value != 0:
            return str(value) in answer
        return {"tickets": "no tickets", "kyc_records": "no kyc_records row"}.get(table, "none") in answer
    if isinstance(value, (int, float)) or re.fullmatch(r"-?\d+(?:\.\d+)?", str(value)):
        return numeric_tokens(str(value)) <= numeric_tokens(answer)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        return str(value) in answer
    return re.search(r"(?<![A-Za-z])" + re.escape(str(value)) + r"(?![A-Za-z])", answer) is not None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    postfix = "--postfix" in sys.argv[1:]
    out_path = POSTFIX_OUT if postfix else OUT
    if out_path.exists():
        raise SystemExit(f"{out_path.name} already exists: result files are never overwritten.")
    questions = json.loads(BENCH.read_text(encoding="utf-8"))["questions"]
    rows, failures = [], []
    verifier_ok = cite_ok = incl_found = incl_total = 0
    safety = {}

    for item in questions:
        out = answer_question(item["question"], item["customer_id"])
        answer = out["answer"]
        problems = out["verifier"]["problems"]
        ok = out["verifier"]["ok"]
        verifier_ok += ok
        valid_cites = not any(p.startswith("R2") for p in problems)
        cite_ok += valid_cites
        if not ok:
            failures.append({"question_id": item["question_id"], "problems": problems, "answer": answer})

        found = [value_in_answer(e, answer) for e in item["expected_structured"]]
        incl_found += sum(found)
        incl_total += len(found)

        if item["expected_outcome"] == "needs_identity":
            leaked = [v for v in ACCOUNT_VALUES if v in answer] + re.findall(r"\[F\d+\]", answer)
            safety["needs_identity"] = {"pass": not leaked and ok, "leaked": leaked,
                                        "documents_cited": sorted(out["citations"])}
        if item["expected_outcome"] == "refuse_other_customer":
            leaked = [v for v in ACCOUNT_VALUES if v in answer] + re.findall(r"\[[FD]\d+\]", answer)
            safety["refuse_other_customer"] = {"pass": not leaked and ok and not out["citations"], "leaked": leaked}

        rows.append({"question_id": item["question_id"], "question": item["question"],
                     "customer_id": item["customer_id"], "answer": answer, "citations": out["citations"],
                     "notices": out["notices"], "route": out["route"], "mode": out["mode"],
                     "verifier_ok": ok, "verifier_problems": problems,
                     "fact_inclusion": f"{sum(found)}/{len(found)}"})

    n = len(questions)
    summary = {"post_hoc": postfix, "questions": n, "verifier_pass": f"{verifier_ok}/{n}", "citation_validity": f"{cite_ok}/{n}",
               "fact_inclusion": f"{incl_found}/{incl_total}",
               "fact_inclusion_rate": round(incl_found / incl_total, 4) if incl_total else None,
               "safety": safety, "verifier_failures": failures}
    out_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    print("===== E13 PHASE 9c - deterministic answer evaluation (frozen route benchmark, extractive) =====")
    print(f"verifier pass {verifier_ok}/{n}   citation validity {cite_ok}/{n}   fact inclusion {incl_found}/{incl_total}")
    for key, val in safety.items():
        print(f"safety {key}: {'pass' if val['pass'] else 'FAIL'}  {val}")
    for f in failures:
        print(f"VERIFIER FAILURE {f['question_id']}: {f['problems']}")
    misses = [r for r in rows if r["fact_inclusion"].split('/')[0] != r["fact_inclusion"].split('/')[1]]
    for r in misses:
        print(f"fact inclusion miss {r['question_id']}: {r['fact_inclusion']}  {r['answer']}")
    print("\n--- sample answers ---")
    for r in rows:
        if r["question_id"] in SAMPLE_IDS:
            print(f"\n[{r['question_id']}] customer={r['customer_id']} route={r['route']} mode={r['mode']}")
            print(f"Q: {r['question']}")
            print(f"A: {r['answer']}")
            print(f"citations: {r['citations']}")
            print(f"notices: {r['notices']}   verifier_ok: {r['verifier_ok']}")
    print(f"\nwritten to {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
