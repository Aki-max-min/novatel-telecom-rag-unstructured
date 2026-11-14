"""
Part 4: reconcile the error-cause labels (analysis only; no generation; the labelling rule is NOT changed).

    .venv_colpali/Scripts/python.exe eval/final_ablation/fa_reconcile.py

1. Records which code produced the v3 table (eval/perf_report/run_report.py::classify at commit dc481b6) and the KG-hardening table
   (the same function, imported, at commit 6956902): `git log` / `git diff` of the file.
2. Applies the CURRENT classify to (a) the v3 raw/scored C records with the v3 B2 of the same run as reference, (b) the KG-hardening C_V0
   records with the KG-hardening B2 as reference, and (c) every arm of results/final_ablation/ when scored; compares (a) with
   results/perf_report/error_table.csv and (b) with results/kg_hardening_eval/error_table.csv row by row.
3. Lists, per (question, run), where the v3 C label differs from the C_V0 label and what differs in the two raw records (route, doc_top10,
   structured ids, prompt documents, answer, correctness), so that the cause of the split can be stated as verified or as inference.

Writes results/final_ablation/error_label_reconciliation.md (+ .json).
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_fa as fa  # noqa: E402

h = fa.h
import run_report as rr  # noqa: E402  (eval/perf_report/run_report.py: the v3 report module, classify + CAUSES)

RUNS = [1, 2, 3]
RULE_ARM = {"A": None, "B": "B", "B2": "B2", "R": "router", "O": "ontology", "G0": "docgraph", "G1": "docgraph", "G1L": "docgraph",
            "C_V0": "C", "C_V1": "C", "C_V1_links": "C"}


def _git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=fa.ROOT).stdout.strip()


def load_arm(raw_path: Path, scored_path: Path, arms: set[str], prefix: str = "") -> tuple[dict, dict]:
    raw = {(prefix + r["arm"], r["id"], r["run"]): r for r in h.read_jsonl(raw_path) if r["arm"] in arms}
    scored = {(prefix + s["arm"], s["id"], s["run"]): s for s in h.read_jsonl(scored_path) if s["arm"] in arms}
    return raw, scored


def label(arm_rule: str, qs, raw, scored, arm: str, ref_arm: str | None) -> dict:
    """(id, run) -> (cause, detail) for every answer of `arm` with correctness < 2, with `ref_arm` of the same run as reference."""
    out = {}
    for r in RUNS:
        for qid, q in qs.items():
            key = (arm, qid, r)
            if key not in scored or scored[key]["correctness"] is None or scored[key]["correctness"] == 2:
                continue
            ref = raw.get((ref_arm, qid, r)) if ref_arm else None
            cause, detail = rr.classify(arm_rule, q, raw[key], scored[key], ref, scored.get((ref_arm, qid, r)) if ref_arm else None)
            if arm_rule == "B" and cause in ("router", "graph"):
                cause = "model"            # the v3 report's remap for B (no router, no layer)
            out[(qid, r)] = (cause, detail, scored[key]["correctness"])
    return out


def read_table(path: Path, arm: str) -> dict:
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["arm"] == arm:
                out[(row["id"], int(row["run"]))] = (row["cause"], row["detail"], int(row["correctness"]))
    return out


def counts(lbl: dict) -> dict:
    c = Counter(v[0] for v in lbl.values())
    return {k: c.get(k, 0) for k in rr.CAUSES} | {"total": sum(c.values())}


def record_diff(a: dict, b: dict) -> dict:
    pa, pb = rr.prompt_doc_ids(a), rr.prompt_doc_ids(b)
    return {"route_same": (a.get("route") or {}).get("final") == (b.get("route") or {}).get("final"),
            "doc_top10_same": a["doc_top10"] == b["doc_top10"], "structured_ids_same": a["structured_ids"] == b["structured_ids"],
            "structured_status_same": (a.get("structured_status") or {}).get("table") == (b.get("structured_status") or {}).get("table"),
            "prompt_docs_same": pa == pb, "prompt_sql_rows_same": [e["record_id"] for e in a["evidence"] if e["source"] == "structured"] == [e["record_id"] for e in b["evidence"] if e["source"] == "structured"],
            "answer_same": a["answer"] == b["answer"], "added_chunks_same": ((a.get("semantic") or {}).get("added_chunks") or []) == ((b.get("semantic") or {}).get("added_chunks") or [])}


def main() -> None:
    qs = {q["id"]: q for q in h.load_questions()}
    code = {"rule_file": "eval/perf_report/run_report.py (function classify, CAUSES, error_analysis)",
            "v3_table_commit": "dc481b6 (Measurement 3/3; results/perf_report/error_table.csv and metrics.json written by this code)",
            "kg_table_commit": "6956902 (eval/kg_hardening_eval/run_report.py imports eval/perf_report/run_report.classify unchanged)",
            "last_change_of_rule_file": _git("log", "-n", "1", "--format=%h %ad %s", "--date=short", "--", "eval/perf_report/run_report.py"),
            "diff_dc481b6_HEAD_rule_file": _git("diff", "--stat", "dc481b6", "HEAD", "--", "eval/perf_report/run_report.py") or "(empty: identical)",
            "kg_call": "rr.classify('C' if arm in C_ARMS else 'B2', q, raw[key], scored[key], ref=B2 same run, scored B2)",
            "v3_call": "classify(arm, q, raw[key], scored[key], ref=B2 same run if arm == 'C' else None, scored B2); B's router/graph remapped to model"}

    # ---- (a) v3 C re-labelled with the current rule vs the v3 table --------------------------------------------------------------------
    v3_raw, v3_scored = load_arm(fa.V3_RES / "raw_answers.jsonl", fa.V3_RES / "scored_answers.jsonl", {"B", "B2", "C"})
    v3_c_now = label("C", qs, v3_raw, v3_scored, "C", "B2")
    v3_b_now = label("B", qs, v3_raw, v3_scored, "B", None)
    v3_c_file = read_table(fa.V3_RES / "error_table.csv", "C")
    v3_b_file = read_table(fa.V3_RES / "error_table.csv", "B")
    a_mismatch = [(k, v3_c_file.get(k), v3_c_now.get(k)) for k in set(v3_c_file) | set(v3_c_now) if (v3_c_file.get(k) or (None,))[0] != (v3_c_now.get(k) or (None,))[0]]
    a_mismatch_b = [(k, v3_b_file.get(k), v3_b_now.get(k)) for k in set(v3_b_file) | set(v3_b_now) if (v3_b_file.get(k) or (None,))[0] != (v3_b_now.get(k) or (None,))[0]]

    # ---- (b) KG-hardening C_V0 re-labelled vs its table ---------------------------------------------------------------------------------
    kg_raw, kg_scored = fa.load_reused(check_counts=False)
    cv0_now = label("C", qs, kg_raw, kg_scored, "C_V0", "B2")
    cv0_file = read_table(fa.KG_RES / "error_table.csv", "C_V0")
    b_mismatch = [(k, cv0_file.get(k), cv0_now.get(k)) for k in set(cv0_file) | set(cv0_now) if (cv0_file.get(k) or (None,))[0] != (cv0_now.get(k) or (None,))[0]]

    # ---- (c) v3 C vs C_V0 under the same rule: per-question label differences -----------------------------------------------------------
    diffs = []
    for key in sorted(set(v3_c_now) | set(cv0_now), key=lambda k: (RUNS.index(k[1]), list(qs).index(k[0]))):
        a, b = v3_c_now.get(key), cv0_now.get(key)
        if (a or (None,))[0] == (b or (None,))[0]:
            continue
        ra, rb = v3_raw.get(("C",) + key), kg_raw.get(("C_V0",) + key)
        diffs.append({"id": key[0], "run": key[1], "category": qs[key[0]]["category"], "v3_C": a, "C_V0": b,
                      "records": record_diff(ra, rb) if ra and rb else None,
                      "v3_structured_ids": ra["structured_ids"][:6] if ra else None, "C_V0_structured_ids": rb["structured_ids"][:6] if rb else None,
                      "v3_prompt_sql_rows": [e["record_id"] for e in ra["evidence"] if e["source"] == "structured"][:6] if ra else None,
                      "C_V0_prompt_sql_rows": [e["record_id"] for e in rb["evidence"] if e["source"] == "structured"][:6] if rb else None})
    # which raw fields differ between v3 C and C_V0 over ALL 126 pairs (not only where labels differ)
    field_diff = Counter()
    for r in RUNS:
        for qid in qs:
            ra, rb = v3_raw.get(("C", qid, r)), kg_raw.get(("C_V0", qid, r))
            if ra and rb:
                for k_, same in record_diff(ra, rb).items():
                    field_diff[k_] += (not same)
    corr_diff = [(qid, r, v3_scored[("C", qid, r)]["correctness"], kg_scored[("C_V0", qid, r)]["correctness"]) for r in RUNS for qid in qs
                 if ("C", qid, r) in v3_scored and ("C_V0", qid, r) in kg_scored and v3_scored[("C", qid, r)]["correctness"] != kg_scored[("C_V0", qid, r)]["correctness"]]

    # ---- new arms, when scored -------------------------------------------------------------------------------------------------------------
    new_counts = {}
    if fa.SCORED.exists():
        n_raw, n_sc = load_arm(fa.RAW, fa.SCORED, set(fa.ARMS_NEW))
        n_raw.update({k: v for k, v in kg_raw.items() if k[0] == "B2"}); n_sc.update({k: v for k, v in kg_scored.items() if k[0] == "B2"})
        for arm in fa.ARMS_NEW:
            if RULE_ARM[arm] is None or not any(k[0] == arm for k in n_sc):
                continue
            ref = "B2" if arm in ("R", "O", "G0", "G1", "G1L") else None
            new_counts[arm] = counts(label(RULE_ARM[arm], qs, n_raw, n_sc, arm, ref))
        for arm in fa.ARMS_REUSED:
            ref = "B2" if arm != "B2" else None
            new_counts[arm] = counts(label(RULE_ARM[arm], qs, kg_raw, kg_scored, arm, ref))

    out = {"code": code,
           "v3_C_table_vs_current_rule": {"table": counts(v3_c_file), "re_labelled_now": counts(v3_c_now), "n_label_mismatches": len(a_mismatch), "mismatches": a_mismatch[:20]},
           "v3_B_table_vs_current_rule": {"table": counts(v3_b_file), "re_labelled_now": counts(v3_b_now), "n_label_mismatches": len(a_mismatch_b)},
           "kg_C_V0_table_vs_current_rule": {"table": counts(cv0_file), "re_labelled_now": counts(cv0_now), "n_label_mismatches": len(b_mismatch), "mismatches": b_mismatch[:20]},
           "v3_C_vs_C_V0_same_rule": {"v3_C": counts(v3_c_now), "C_V0": counts(cv0_now), "n_answers_with_different_label": len(diffs), "per_answer": diffs,
                                      "raw_fields_differing_over_126_pairs": dict(field_diff), "correctness_differs": corr_diff},
           "current_rule_on_every_arm": new_counts}
    (fa.RES / "error_label_reconciliation.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (fa.RES / "error_label_reconciliation.md").write_text(markdown(out), encoding="utf-8")
    print(markdown(out))


def _row(name, c):
    return f"| {name} | " + " | ".join(str(c[k]) for k in rr.CAUSES + ["total"]) + " |"


def markdown(out) -> str:
    head = "| arm (rule applied) | " + " | ".join(rr.CAUSES + ["total"]) + " |\n|---|" + "---|" * (len(rr.CAUSES) + 1)
    L = ["# Error-cause label reconciliation (v3 C vs KG-hardening C_V0)", "",
         "Analysis only. The labelling rule (`eval/perf_report/run_report.classify`) is not changed here.", "", "## 1. Which code produced which table", ""]
    for k, v in out["code"].items():
        L.append(f"* **{k}**: {v}")
    L += ["", "## 2. The same current rule applied to both raw-answer sets", "",
          "### v3 arm C: table on disk vs re-labelled now (reference: v3 B2 of the same run)", "", head,
          _row("v3 C, results/perf_report/error_table.csv", out["v3_C_table_vs_current_rule"]["table"]),
          _row("v3 C, classify() run now", out["v3_C_table_vs_current_rule"]["re_labelled_now"]),
          f"\nAnswers whose label differs between the file and the re-labelling: {out['v3_C_table_vs_current_rule']['n_label_mismatches']}"
          + (f" -> {out['v3_C_table_vs_current_rule']['mismatches']}" if out['v3_C_table_vs_current_rule']['n_label_mismatches'] else " (the file is reproduced exactly)."),
          f"\nv3 arm B: {out['v3_B_table_vs_current_rule']['n_label_mismatches']} label mismatches between file and re-labelling.", "",
          "### KG-hardening arm C_V0: table on disk vs re-labelled now (reference: KG-hardening B2 of the same run)", "", head,
          _row("C_V0, results/kg_hardening_eval/error_table.csv", out["kg_C_V0_table_vs_current_rule"]["table"]),
          _row("C_V0, classify() run now", out["kg_C_V0_table_vs_current_rule"]["re_labelled_now"]),
          f"\nAnswers whose label differs: {out['kg_C_V0_table_vs_current_rule']['n_label_mismatches']}"
          + (f" -> {out['kg_C_V0_table_vs_current_rule']['mismatches']}" if out['kg_C_V0_table_vs_current_rule']['n_label_mismatches'] else " (the file is reproduced exactly)."), "",
          "### Side by side, same rule", "", head, _row("v3 C", out["v3_C_vs_C_V0_same_rule"]["v3_C"]), _row("C_V0 (KG-hardening run)", out["v3_C_vs_C_V0_same_rule"]["C_V0"]), ""]
    s = out["v3_C_vs_C_V0_same_rule"]
    L += ["## 3. Where the two C arms get different labels (same question, same run)", "",
          f"Answers with a different label: {s['n_answers_with_different_label']} of 126 pairs. Over all 126 (question, run) pairs, the raw records differ in: "
          + ", ".join(f"{k.replace('_same', '')} {v}" for k, v in s["raw_fields_differing_over_126_pairs"].items()) + ".",
          f"Correctness differs on {len(s['correctness_differs'])} answers: {s['correctness_differs']}", "",
          "| id | run | cat | v3 C label (corr.) | C_V0 label (corr.) | route same | doc_top10 same | SQL ids same | prompt docs same | prompt SQL rows same | answer same | v3 SQL ids -> C_V0 SQL ids |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in s["per_answer"]:
        rd = d["records"] or {}
        a, b = d["v3_C"] or ("-", "", "-"), d["C_V0"] or ("-", "", "-")
        L.append(f"| {d['id']} | {d['run']} | {d['category']} | {a[0]} ({a[2]}) | {b[0]} ({b[2]}) | {rd.get('route_same')} | {rd.get('doc_top10_same')} | {rd.get('structured_ids_same')} | "
                 f"{rd.get('prompt_docs_same')} | {rd.get('prompt_sql_rows_same')} | {rd.get('answer_same')} | {d['v3_structured_ids']} -> {d['C_V0_structured_ids']} |")
    L += ["", "Detail strings (v3 C / C_V0):", ""]
    for d in s["per_answer"]:
        L.append(f"* {d['id']} run {d['run']}: v3 C `{(d['v3_C'] or ('', ''))[1]}` ; C_V0 `{(d['C_V0'] or ('', ''))[1]}`")
    if out["current_rule_on_every_arm"]:
        L += ["", "## 4. The current rule on every arm of the final ablation (reference B2 of the same run for router/layer arms)", "", head]
        for arm, c in out["current_rule_on_every_arm"].items():
            L.append(_row(arm, c))
    L += ["", "## 5. Reading", "", "(filled in by hand in SUMMARY.md / STATUS.md from the numbers above; see the final report)"]
    return "\n".join(L)


if __name__ == "__main__":
    main()
