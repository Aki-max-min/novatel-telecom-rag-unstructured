"""
Report stage: turns raw_answers.jsonl + scored_answers.jsonl (+ saved router/abstention/index-comparison files) into every output of the measurement.

    python eval/perf_report/run_report.py

Writes (results/perf_report/): metrics.json, error_table.csv, ablation.csv, regressions.md, values.json (+ a .manifest.json next to each; they are copies
of run_manifest.json taken before the first output existed, i.e. recorded on a clean tree).

Definitions (all stated in metrics.json -> "definitions"):
  * 3 runs per arm (temperature 0 / seed 42 is NOT deterministic on this machine, see determinism_check.json). Percentages are the MEAN over runs of the per-run
    percentage; ranges are min-max over runs.
  * correctness % = mean(score)/2 over scorable answers (E14a definition, score 0/1/2). "right" = score 2.
  * paired statistics use per-question "right" = fully correct in the majority (>= 2 of 3) of runs; McNemar exact two-sided; the bootstrap resamples QUESTIONS
    (10,000, seed 20261031) and uses the per-question share of runs that were fully correct, so its CI is in percentage points of the fully-correct rate.
  * error counts are ANSWERS (3 runs x 42 questions per arm) with correctness < 2.
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402

from integration.eval.run_manifest import hardware  # noqa: E402

RES = h.RES
ARMS = h.ARMS
BOOT_SEED = 20261031
BOOT_N = 10_000
CATS = ["db", "syn", "trai", "cross", "multi"]
ROUTER_EVAL = h.ROOT / "data" / "experiments" / "router_eval" / "router_eval_test_20261031T140655Z_final_test.json"
ABSTENTION = h.ROOT / "data" / "experiments" / "system_eval" / "abstention_test_20261031T142243Z_final_test.json"
SCIFACT_CMP = h.ROOT / "docs" / "scifact_index_comparison.json"
GRAPH = h.ROOT / "knowledge_graph" / "output" / "graph.json"
INDEX_META = h.ROOT / "data" / "experiments" / "combined_retrieval_clean" / "vectorstore" / "chunk_metadata.json"
E14A_DOCUMENTED = {"rag_correctness": 79.5, "base_correctness": 45.5}


# ---------------------------------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------------------------------
def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def rng(xs):
    xs = [x for x in xs if x is not None]
    return [min(xs), max(xs)] if xs else None


def fmt_pct(x):
    return "n/a" if x is None else f"{x:.1f}%"


def fmt_delta(x):
    return "n/a" if x is None else f"{x:+.1f} pts"


def fmt_s(x):
    return "n/a" if x is None else f"{x:.1f} s"


def fmt_ratio(x):
    return "n/a" if x is None else f"{x:.3f}"


def fmt_int(x):
    return "n/a" if x is None else f"{int(round(x)):,}"


def mcnemar_exact(w: int, l: int) -> float:
    n = w + l
    if n == 0:
        return 1.0
    k = min(w, l)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * p)


def bootstrap_ci(diffs: list[float], seed: int = BOOT_SEED, n: int = BOOT_N) -> list[float]:
    r = random.Random(seed)
    m = len(diffs)
    means = sorted(sum(diffs[r.randrange(m)] for _ in range(m)) / m * 100 for _ in range(n))
    return [round(means[int(0.025 * n)], 1), round(means[int(0.975 * n) - 1], 1)]


# ---------------------------------------------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------------------------------------------
def load():
    qs = {q["id"]: q for q in h.load_questions()}
    raw = {(r["arm"], r["id"], r["run"]): r for r in h.read_jsonl(h.RAW)}
    scored = {(s["arm"], s["id"], s["run"]): s for s in h.read_jsonl(h.SCORED)}
    return qs, raw, scored


def runs_of(raw, arm):
    return sorted({k[2] for k in raw if k[0] == arm})


def in_subset(q, subset):
    return subset == "all" or (subset == "core" and q["is_core"]) or q["category"] == subset


def arm_metric(arm, subset, field, scored, qs, runs):
    """E14a-style percentage of `field` (score/2 fields or 0/1 rate fields) per run, then mean + range."""
    per_run = []
    for r in runs:
        vals = [scored[(arm, qid, r)].get(field) for qid in qs if in_subset(qs[qid], subset) and (arm, qid, r) in scored]
        if field in ("halluc_ref", "halluc_ctx"):
            per_run.append(h.rate_pct(vals))
        else:
            per_run.append(h.pct_of_two(vals))
    return per_run


# ---------------------------------------------------------------------------------------------------------------------------------
# retrieval + citation + row coverage
# ---------------------------------------------------------------------------------------------------------------------------------
def doc_requirement(q):
    ref = q["reference"]
    return list(ref.get("expected_document_ids") or [])


def retrieval_metrics(arm, qs, raw, runs, subset_ids=None):
    """R@k / MRR@10 over document questions (retrieval is deterministic: run 1 is used; identical across runs is checked and reported)."""
    r = runs[0] if runs else None
    hits = {1: 0, 3: 0, 5: 0, 10: 0}
    mrr, n = 0.0, 0
    for qid, q in qs.items():
        exp = doc_requirement(q)
        if not exp or (subset_ids is not None and qid not in subset_ids) or (arm, qid, r) not in raw:
            continue
        docs = raw[(arm, qid, r)]["doc_top10"]
        n += 1
        for k in hits:
            hits[k] += any(d in exp for d in docs[:k])
        for rank, d in enumerate(docs[:10], 1):
            if d in exp:
                mrr += 1 / rank
                break
    return {"n": n, **{f"R@{k}": (round(hits[k] / n, 4) if n else None) for k in hits}, "MRR@10": round(mrr / n, 4) if n else None,
            "hits": hits}


def retrieval_is_deterministic(arm, qs, raw, runs):
    diffs = []
    for qid in qs:
        lists = [tuple(raw[(arm, qid, r)]["doc_top10"]) for r in runs if (arm, qid, r) in raw]
        if len(set(lists)) > 1:
            diffs.append(qid)
    return diffs


def sql_requirements(q):
    """[(table, record_id | 'aggregate')]: the database rows a correct answer needs."""
    out = []
    if q["reference"]["kind"] == "sql_record" and q.get("gold_sql"):
        gt, table = q["gold_sql"], q["reference"].get("expected_table")
        if gt["kind"] == "rows":
            out += [(table, str(pk)) for pk in gt["anchors"]]
        elif gt["kind"] == "aggregate_count":
            out.append((table, "aggregate"))
    for f in q.get("gold_facts", []):
        if f.get("sql"):
            key = (f["sql"]["table"], str(f["sql"]["record_id"]))
            if key not in out:
                out.append(key)
    return out


def rows_in_prompt(rec, req):
    table, rid = req
    for e in rec["evidence"]:
        if e["source"] != "structured" or e["dataset"] != table:
            continue
        if rid == "aggregate" or str(e["record_id"]) == rid:
            return True
    return False


def db_rowcov(arm, qs, raw, runs):
    per_run = []
    for r in runs:
        need = cov = 0
        for qid, q in qs.items():
            reqs = sql_requirements(q)
            if not reqs or (arm, qid, r) not in raw:
                continue
            for req in reqs:
                need += 1
                cov += rows_in_prompt(raw[(arm, qid, r)], req)
        per_run.append(round(100 * cov / need, 1) if need else None)
    return per_run


def citation_metrics(arm, scored, qs, runs):
    per_run = {"cov": [], "correct": [], "unsup": []}
    totals = {"checked": 0, "skipped": 0, "sentences": 0, "cited": 0, "supported_cited": 0, "weak": 0, "unsupported": 0}
    for r in runs:
        sents = cited = sup = unsup = 0
        for qid in qs:
            s = scored.get((arm, qid, r))
            c = (s or {}).get("citation")
            if not c:
                continue
            if not c["checked"]:
                totals["skipped"] += 1
                continue
            totals["checked"] += 1
            sents += c["n_sentences"]; cited += c["n_cited"]; sup += c["n_cited_supported"]; unsup += c["n_unsupported"]
            totals["weak"] += c["n_weak"]
        per_run["cov"].append(round(100 * cited / sents, 1) if sents else None)
        per_run["correct"].append(round(100 * sup / cited, 1) if cited else None)
        per_run["unsup"].append(round(100 * unsup / sents, 1) if sents else None)
        totals["sentences"] += sents; totals["cited"] += cited; totals["supported_cited"] += sup; totals["unsupported"] += unsup
    return per_run, totals


# ---------------------------------------------------------------------------------------------------------------------------------
# right / wrong, paired statistics
# ---------------------------------------------------------------------------------------------------------------------------------
def right_rates(arm, qs, scored, runs):
    """question -> share of runs that were fully correct (None if never scorable)."""
    out = {}
    for qid in qs:
        v = [scored[(arm, qid, r)]["correctness"] for r in runs if (arm, qid, r) in scored and scored[(arm, qid, r)]["correctness"] is not None]
        out[qid] = None if not v else sum(1 for x in v if x == 2) / len(v)
    return out


def paired(a_arm, b_arm, qs, scored, runs):
    """C (a) versus another arm (b): wins = a right & b wrong (majority of runs)."""
    ra, rb = right_rates(a_arm, qs, scored, runs), right_rates(b_arm, qs, scored, runs)
    wins = losses = ties = 0
    diffs, win_ids, loss_ids = [], [], []
    for qid in qs:
        if ra[qid] is None or rb[qid] is None:
            continue
        a_right, b_right = ra[qid] > 0.5, rb[qid] > 0.5
        diffs.append(ra[qid] - rb[qid])
        if a_right and not b_right:
            wins += 1; win_ids.append(qid)
        elif b_right and not a_right:
            losses += 1; loss_ids.append(qid)
        else:
            ties += 1
    return {"wins": wins, "losses": losses, "ties": ties, "n_pairs": len(diffs), "discordant": wins + losses,
            "p_mcnemar_exact": round(mcnemar_exact(wins, losses), 4), "small_discordant_note": (wins + losses) < 10,
            "ci95_pts": bootstrap_ci(diffs) if diffs else None, "mean_diff_pts": round(100 * sum(diffs) / len(diffs), 1) if diffs else None,
            "win_ids": win_ids, "loss_ids": loss_ids}


# ---------------------------------------------------------------------------------------------------------------------------------
# error analysis (B and C)
# ---------------------------------------------------------------------------------------------------------------------------------
CITE = re.compile(r"\[(E\d+)\]")


def prompt_doc_ids(rec):
    return [b["doc_id"] or b["record_id"] for b in rec["prompt_blocks"] if b["source"] == "unstructured"]


def classify(arm, q, rec, sc, ref_rec, ref_sc):
    """One cause per wrong answer. Order: retrieval > context > ranking > competing > router > graph > model > scoring, with two stated
    interpretations: (1) 'retrieval' applies only when the needed source was actually searched, an excluded source is 'router';
    (2) when the router or the semantic layer demonstrably changed the outcome relative to B2 (same run), that is recognised first,
    because otherwise those two causes could never be reported."""
    docs_needed = doc_requirement(q)
    all_docs = q["category"] == "multi" and q["subtype"] == "doc_doc"
    sql_needed = sql_requirements(q)
    route = (rec.get("route") or {}).get("final")
    detail = {}
    # needed sources
    need_docs, need_sql = bool(docs_needed), bool(sql_needed)
    # --- router (needed source excluded or abstained) -------------------------------------------------------------------
    if arm in ("router", "C") and rec.get("route"):
        excluded = (need_sql and route == "unstructured") or (need_docs and route == "structured") or route == "out_of_scope"
        if excluded:
            return "router", f"route={route}; needed: {'sql ' if need_sql else ''}{'docs' if need_docs else ''}"
    # --- retrieval ---------------------------------------------------------------------------------------------------------
    def docs_retrieved():
        if not need_docs:
            return True
        return all(d in rec["doc_top10"] for d in docs_needed) if all_docs else any(d in rec["doc_top10"] for d in docs_needed)

    def sql_retrieved():
        if not need_sql:
            return True
        st = rec.get("structured_status") or {}
        table = st.get("table")
        ids = set(rec["structured_ids"])
        return all(t == table and (rid == "aggregate" and bool(ids) or rid in ids) for t, rid in sql_needed)

    # layer displacement is recognised before generic retrieval failure (see docstring)
    if arm in ("ontology", "docgraph", "C") and ref_rec is not None:
        ref_docs_ok = (all(d in ref_rec["doc_top10"] for d in docs_needed) if all_docs else any(d in ref_rec["doc_top10"] for d in docs_needed)) if need_docs else True
        if need_docs and ref_docs_ok and not docs_retrieved():
            return "graph", "gold document retrieved by B2 but displaced here (semantic layer)"
    if not (docs_retrieved() and sql_retrieved()):
        return "retrieval", f"docs_retrieved={docs_retrieved()} sql_retrieved={sql_retrieved()}"
    # --- context ----------------------------------------------------------------------------------------------------------------
    pdocs = prompt_doc_ids(rec)
    docs_in_prompt = (not need_docs) or (all(d in pdocs for d in docs_needed) if all_docs else any(d in pdocs for d in docs_needed))
    sql_in_prompt = (not need_sql) or all(rows_in_prompt(rec, rq) for rq in sql_needed)
    if not (docs_in_prompt and sql_in_prompt):
        return "context", f"docs_in_prompt={docs_in_prompt} sql_rows_in_prompt={sql_in_prompt}"
    # --- ranking / competing (documents) ----------------------------------------------------------------------------------------
    cited = [b for b in rec["prompt_blocks"] if b["id"] in set(CITE.findall(rec["answer"]))]
    cited_docs = [b["doc_id"] or b["record_id"] for b in cited if b["source"] == "unstructured"]
    distractor_cited = [d for d in cited_docs if d not in docs_needed]
    if need_docs and distractor_cited:
        first_is_gold = bool(pdocs) and pdocs[0] in docs_needed
        return ("competing", f"gold first, but cited {distractor_cited[:2]}") if first_is_gold else \
               ("ranking", f"gold present but not first; cited distractor {distractor_cited[:2]}")
    # --- graph evidence led it wrong (semantic arms) ------------------------------------------------------------------------------
    if arm in ("ontology", "docgraph", "C"):
        added_cited = [e["record_id"] for e in rec["evidence"] if e.get("semantic_added") and e["id"] in set(CITE.findall(rec["answer"]))]
        if added_cited:
            return "graph", f"answer cites chunk(s) added by the semantic layer: {added_cited[:2]}"
    # --- scoring (narrow, inferred): all deterministic gold anchors present but a judge scored it < 2 -----------------------------------
    if sc.get("facts") and all(f["present"] for f in sc["facts"] if f["method"] == "deterministic anchors") \
            and any(f["method"] != "deterministic anchors" and not f["present"] for f in sc["facts"]):
        return "scoring", "all deterministic anchors present; only a judge-scored fact is missing (inferred, needs human review)"
    return "model", "right evidence in the prompt, answer wrong/partial/uncited"


CAUSES = ["retrieval", "context", "competing", "ranking", "model", "router", "graph", "scoring"]


def error_analysis(qs, raw, scored, runs):
    rows, counts = [], {a: {c: 0 for c in CAUSES} for a in ("B", "C")}
    for arm in ("B", "C"):
        for r in runs:
            for qid, q in qs.items():
                key = (arm, qid, r)
                if key not in scored or scored[key]["correctness"] is None or scored[key]["correctness"] == 2:
                    continue
                ref = raw.get(("B2", qid, r)) if arm == "C" else None
                cause, detail = classify(arm, q, raw[key], scored[key], ref, scored.get(("B2", qid, r)))
                if arm == "B" and cause in ("router", "graph"):
                    cause = "model"          # B has no router and no semantic layer: these causes cannot apply
                counts[arm][cause] += 1
                rows.append({"arm": arm, "run": r, "id": qid, "category": q["category"], "correctness": scored[key]["correctness"],
                             "cause": cause, "detail": detail})
    return rows, counts


# ---------------------------------------------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------------------------------------------
def main() -> None:
    qs, raw, scored = load()
    runs_by_arm = {a: runs_of(raw, a) for a in ARMS + [h.REPRO_ARM]}
    runs = runs_by_arm["B"]
    missing_scored = [k for k in raw if k not in scored]
    if missing_scored:
        print(f"WARNING: {len(missing_scored)} raw records are not scored yet; run run_score.py score first")
    manifest = json.loads((RES / "run_manifest.json").read_text(encoding="utf-8"))
    det = json.loads((RES / "determinism_check.json").read_text(encoding="utf-8")) if (RES / "determinism_check.json").exists() else None
    counts_q = json.loads((h.PERF / "question_counts.json").read_text(encoding="utf-8"))

    M: dict = {"definitions": __doc__, "runs_per_arm": {a: len(r) for a, r in runs_by_arm.items()},
               "determinism_check": {k: det[k] for k in ("n_questions", "n_identical_answers", "all_deterministic", "decision")} if det else None,
               "counts": {k: v for k, v in counts_q.items() if k not in ("dropped", "unreviewed_by_category")}, "arms": {}}

    # ---- per-arm metrics -------------------------------------------------------------------------------------------------------
    for arm in ARMS + [h.REPRO_ARM]:
        rr = runs_by_arm[arm]
        if not rr:
            continue
        a = {"n_records": sum(1 for k in raw if k[0] == arm)}
        for subset in ["all", "core"] + CATS:
            a[f"correctness.{subset}"] = arm_metric(arm, subset, "correctness", scored, qs, rr)
        for field in ("relevance", "groundedness", "halluc_ref", "halluc_ctx"):
            a[field] = arm_metric(arm, "all", field, scored, qs, rr)
            a[field + ".core"] = arm_metric(arm, "core", field, scored, qs, rr)
        recs = [raw[k] for k in raw if k[0] == arm]
        lat = [x["latency_s"] for x in recs]
        a["latency_median_s"] = round(statistics.median(lat), 2) if lat else None
        a["latency_p95_s"] = h.p95(lat)
        a["prompt_tokens_median"] = statistics.median([x["prompt_tokens"] for x in recs if x["prompt_tokens"]]) if any(x["prompt_tokens"] for x in recs) else None
        a["n_cached_records"] = sum(1 for x in recs if x.get("cached"))
        a["n_abstained"] = sum(1 for x in recs if x.get("abstained"))
        a["n_parse_errors_in_judge"] = sum(1 for k, s in scored.items() if k[0] == arm and s.get("judge_parse_error"))
        if arm not in ("A",):
            a["retrieval_docq"] = retrieval_metrics(arm, qs, raw, rr)
            a["retrieval_core14"] = retrieval_metrics(arm, qs, raw, rr, {q for q in qs if qs[q]["is_core"]})
            a["retrieval_deterministic_across_runs"] = not retrieval_is_deterministic(arm, qs, raw, rr)
            a["db_rowcov"] = db_rowcov(arm, qs, raw, rr)
        if arm in ("B", "C"):
            per_run, totals = citation_metrics(arm, scored, qs, rr)
            a["citation"] = {"per_run": per_run, "totals": totals}
        M["arms"][arm] = a

    # ---- paired statistics -----------------------------------------------------------------------------------------------------
    pairs = {"CB": ("C", "B"), "CA": ("C", "A"), "CB2": ("C", "B2")}
    M["paired"] = {k: paired(a, b, qs, scored, runs) for k, (a, b) in pairs.items() if runs_by_arm.get(a) and runs_by_arm.get(b)}

    # ---- repro / scifact ------------------------------------------------------------------------------------------------------------
    core = {q for q in qs if qs[q]["is_core"]}
    if runs_by_arm[h.REPRO_ARM]:
        off = arm_metric(h.REPRO_ARM, "core", "correctness", scored, qs, runs_by_arm[h.REPRO_ARM])
        on = M["arms"]["B"]["correctness.core"]
        M["repro_E14a"] = {"B_scifact_off_core22_per_run": off, "B_scifact_off_core22_mean": mean(off), "B_scifact_on_core22_per_run": on,
                           "B_scifact_on_core22_mean": mean(on), "documented_E14a_rag": E14A_DOCUMENTED["rag_correctness"],
                           "diff_off_minus_on_pts": round(mean(off) - mean(on), 1) if mean(off) is not None and mean(on) is not None else None,
                           "retrieval_off_core14": retrieval_metrics(h.REPRO_ARM, qs, raw, runs_by_arm[h.REPRO_ARM], core),
                           "retrieval_on_core14": retrieval_metrics("B", qs, raw, runs, core)}

    # ---- error analysis -----------------------------------------------------------------------------------------------------------------
    err_rows, err_counts = error_analysis(qs, raw, scored, runs)
    M["error_analysis"] = {"counts": err_counts, "totals": {a: sum(c.values()) for a, c in err_counts.items()}}
    with open(RES / "error_table.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["arm", "run", "id", "category", "correctness", "cause", "detail"])
        w.writeheader(); w.writerows(err_rows)

    # ---- ablation ------------------------------------------------------------------------------------------------------------------------
    abl = [("B", "B", "E14a configuration (shared 6-block budget)"), ("budget", "B2", "B + per-source budget 5 db + 3 doc"),
           ("router", "router", "B2 + router"), ("ontology", "ontology", "B2 + ontology term normalisation only"),
           ("docgraph", "docgraph", "B2 + document-graph expansion only"), ("kg", None, "B2 + structured KG"),
           ("C", "C", "B2 + semantic layer + router + citation check")]
    abl_rows = []
    for name, arm, desc in abl:
        if arm is None:
            abl_rows.append({"component": name, "arm": "-", "description": desc, "correctness_all": "not run (not wired into retrieval)",
                             "correctness_all_range": "", "correctness_core22": "", "groundedness": "not run (not wired into retrieval)"})
            continue
        a = M["arms"].get(arm)
        abl_rows.append({"component": name, "arm": arm, "description": desc,
                         "correctness_all": mean(a["correctness.all"]) if a else None, "correctness_all_range": rng(a["correctness.all"]) if a else None,
                         "correctness_core22": mean(a["correctness.core"]) if a else None, "groundedness": mean(a["groundedness"]) if a else None})
    with open(RES / "ablation.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(abl_rows[0].keys()))
        w.writeheader(); w.writerows(abl_rows)
    M["ablation"] = abl_rows

    # ---- regressions (right in B2, wrong in C) -------------------------------------------------------------------------------------
    reg_lines = ["# Regressions: right in B2, wrong in C", "",
                 "Question level (right = fully correct in a majority of the 3 runs). If C were not better than B2 this file would say so; see the summary below.", ""]
    if "CB2" in M["paired"]:
        p = M["paired"]["CB2"]
        reg_lines += [f"Summary C vs B2: wins {p['wins']}, losses {p['losses']}, ties {p['ties']}, McNemar exact p = {p['p_mcnemar_exact']}"
                      f"{' (fewer than 10 discordant pairs: low power)' if p['small_discordant_note'] else ''}; paired bootstrap 95% CI of the difference "
                      f"{p['ci95_pts']} pts (mean {p['mean_diff_pts']:+.1f} pts).", ""]
        for qid in p["loss_ids"]:
            q = qs[qid]
            reg_lines += [f"## {qid} ({q['category']}) - {q['query']}", ""]
            for r in runs:
                kc, kb = ("C", qid, r), ("B2", qid, r)
                if kc not in raw or kb not in raw:
                    continue
                cause = next((e["cause"] + ": " + e["detail"] for e in err_rows if e["arm"] == "C" and e["id"] == qid and e["run"] == r), "(C correct in this run)")
                route = (raw[kc].get("route") or {}).get("final")
                reg_lines += [f"**Run {r}** - B2 correctness {scored[kb]['correctness']}, C correctness {scored[kc]['correctness']}, C route `{route}`, suspected cause: {cause}", "",
                              f"- B2 answer: {raw[kb]['answer'][:700]!r}", f"- C answer: {raw[kc]['answer'][:700]!r}",
                              f"- C documents in prompt: {prompt_doc_ids(raw[kc])}; added by the layer: {((raw[kc].get('semantic') or {}).get('added_chunks') or [])[:4]}", ""]
        if not p["loss_ids"]:
            reg_lines += ["No question is right in B2 and wrong in C.", ""]
    (RES / "regressions.md").write_text("\n".join(reg_lines), encoding="utf-8")

    # ---- saved router / abstention / scifact / graph -------------------------------------------------------------------------------------
    router = json.loads(ROUTER_EVAL.read_text(encoding="utf-8"))
    by = {r["router"]: r for r in router["results"]}
    M["router_saved"] = {"file": str(ROUTER_EVAL.relative_to(h.ROOT)).replace("\\", "/"), "n": router["n"],
                         "rows": {k: ({"acc": v["metrics"]["accuracy"], "macro_f1": v["metrics"]["macro_f1"], "hybrid_recall": v["metrics"]["hybrid_recall"],
                                       "oos_recall": v["metrics"]["out_of_scope_recall"], "latency_ms": v["metrics"]["latency_ms"]} if v["status"] == "evaluated" else v["status"])
                                  for k, v in by.items()}}
    ab = json.loads(ABSTENTION.read_text(encoding="utf-8"))["summary"]
    M["abstention_saved"] = {"file": str(ABSTENTION.relative_to(h.ROOT)).replace("\\", "/"), "n_should_abstain": ab["n_should_abstain"],
                             "precision": ab["abstention_precision"], "recall": ab["abstention_recall"], "false_abstention_rate": ab["false_abstention_rate"],
                             "false_abstentions": ab["false_abstentions"]}
    cmp_ = json.loads(SCIFACT_CMP.read_text(encoding="utf-8"))
    g = json.loads(GRAPH.read_text(encoding="utf-8"))
    key = {n["id"]: n["key"] for n in g["nodes"]}
    idx = {m["document_id"] for m in json.loads(INDEX_META.read_text(encoding="utf-8"))}
    rel = [(key[e["source"]], key[e["target"]]) for e in g["edges"] if e["type"] == "RELATED_TO"]
    resolving = sum(1 for a_, b_ in rel if a_ in idx and b_ in idx)
    M["related_to"] = {"edges": len(rel), "resolving": resolving}
    integ = json.loads((RES / "judge_integrity.json").read_text(encoding="utf-8")) if (RES / "judge_integrity.json").exists() else None
    M["judge_integrity"] = None if not integ else {k: integ[k] for k in ("n_sample", "n_pool", "seed", "same_model_uncached_rejudge", "second_model_rejudge", "reading")}

    fa = RES / "false_abstentions.json"
    M["false_abstention_diagnosis"] = json.loads(fa.read_text(encoding="utf-8")) if fa.exists() else "not run (diagnose_false_abstentions.py has not been executed)"
    (RES / "metrics.json").write_text(json.dumps(M, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # ---- values.json -------------------------------------------------------------------------------------------------------------------------
    V = build_values(M, manifest, counts_q, cmp_, integ, err_counts)
    expected = expected_keys()
    missing = [k for k in expected if k not in V]
    extra = [k for k in V if k not in expected]
    empty = [k for k in expected if k in V and (V[k] is None or str(V[k]).strip() == "")]
    (RES / "values.json").write_text(json.dumps({k: V[k] for k in expected if k in V}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"values.json: {len(V)} generated, {len(expected)} expected | missing {missing} | extra {extra} | empty {empty}")
    # manifests next to every output
    for name in ("metrics.json", "error_table.csv", "ablation.csv", "regressions.md", "values.json", "human_review_sample.csv", "raw_answers.jsonl", "scored_answers.jsonl"):
        p = RES / name
        if p.exists():
            (RES / (p.stem + ".manifest.json")).write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------------------------
def expected_keys() -> list[str]:
    k = []
    for m in ["correctness", "relevance", "halluc_ref"]:
        k += [f"{m}.{a}" for a in ["A", "B", "C", "dCB"]]
    for m in ["groundedness", "halluc_ctx", "cite_cov", "cite_correct", "unsupported"]:
        k += [f"{m}.{a}" for a in ["B", "C", "dCB"]]
    k += [f"core.correctness.{a}" for a in "ABC"]
    for c in ["db", "syn", "trai", "cross", "multi"]:
        k += [f"cat_{c}.{a}" for a in ["n", "A", "B", "C"]]
    for m in ["r1", "r3", "r5", "mrr10", "db_rowcov"]:
        k += [f"{m}.B", f"{m}.C"]
    for c in ["B", "budget", "router", "ontology", "docgraph", "kg", "C"]:
        k += [f"abl.{c}.correctness", f"abl.{c}.groundedness"]
    for r in ["rule", "embedding", "nli", "ollama", "laya_zs", "laya_ft"]:
        k += [f"router.{r}.{x}" for x in ["acc", "hybrid", "lat"]]
    for m in ["latency_med", "latency_p95", "ptok"]:
        k += [f"{m}.{a}" for a in "ABC"]
    for c in ["retrieval", "context", "competing", "ranking", "model", "router", "graph", "scoring"]:
        k += [f"err.{c}.B", f"err.{c}.C"]
    k += ["err_total.B", "err_total.C"]
    for s in ["CB", "CA", "CB2"]:
        k += [f"{x}_{s}" for x in ["wins", "losses", "ties", "p", "ci"]]
    k += ["review_date", "llm_tag", "hardware", "n_total", "n_db", "n_syn", "n_trai", "n_cross", "n_core", "n_new", "n_docq", "n_router_test",
          "n_oos", "abst_prec", "abst_rec", "false_abst", "armB_components", "armC_components", "connected_list", "not_connected_list",
          "human_review_status", "review_status_new", "repro_E14a", "scifact_effect", "dangling_links"]
    return k


def build_values(M, manifest, counts_q, cmp_, integ, err_counts) -> dict:
    V: dict = {}
    A = M["arms"]

    def val(arm, key):
        return mean(A[arm][key]) if arm in A and key in A[arm] else None

    def put_arm_metric(prefix, key, arms, delta=True):
        for arm in arms:
            V[f"{prefix}.{arm}"] = fmt_pct(val(arm, key))
        if delta:
            b, c = val("B", key), val("C", key)
            V[f"{prefix}.dCB"] = fmt_delta(None if b is None or c is None else c - b)

    put_arm_metric("correctness", "correctness.all", ["A", "B", "C"])
    put_arm_metric("relevance", "relevance", ["A", "B", "C"])
    put_arm_metric("halluc_ref", "halluc_ref", ["A", "B", "C"])
    put_arm_metric("groundedness", "groundedness", ["B", "C"])
    put_arm_metric("halluc_ctx", "halluc_ctx", ["B", "C"])
    for name, key in (("cite_cov", "cov"), ("cite_correct", "correct"), ("unsupported", "unsup")):
        vals = {arm: mean(A[arm]["citation"]["per_run"][key]) if arm in A and "citation" in A[arm] else None for arm in ("B", "C")}
        for arm in ("B", "C"):
            V[f"{name}.{arm}"] = fmt_pct(vals[arm])
        V[f"{name}.dCB"] = fmt_delta(None if vals["B"] is None or vals["C"] is None else vals["C"] - vals["B"])
    for arm in "ABC":
        V[f"core.correctness.{arm}"] = fmt_pct(val(arm, "correctness.core"))
    for c in CATS:
        V[f"cat_{c}.n"] = str(counts_q["per_category"].get(c, 0))
        for arm in "ABC":
            V[f"cat_{c}.{arm}"] = fmt_pct(val(arm, f"correctness.{c}"))
    for m, key in (("r1", "R@1"), ("r3", "R@3"), ("r5", "R@5"), ("mrr10", "MRR@10")):
        for arm in "BC":
            V[f"{m}.{arm}"] = fmt_ratio(A[arm]["retrieval_docq"][key]) if arm in A else "n/a"
    for arm in "BC":
        V[f"db_rowcov.{arm}"] = fmt_pct(val(arm, "db_rowcov"))
    for name, arm in (("B", "B"), ("budget", "B2"), ("router", "router"), ("ontology", "ontology"), ("docgraph", "docgraph"), ("C", "C")):
        V[f"abl.{name}.correctness"] = fmt_pct(val(arm, "correctness.all"))
        V[f"abl.{name}.groundedness"] = fmt_pct(val(arm, "groundedness"))
    V["abl.kg.correctness"] = V["abl.kg.groundedness"] = "not run (not wired into retrieval)"
    rs = M["router_saved"]["rows"]
    rmap = {"rule": "rule", "embedding": "embedding", "nli": "zeroshot_nli", "ollama": "ollama_qwen3b", "laya_zs": "laya_zeroshot", "laya_ft": "laya_finetuned"}
    for key, src in rmap.items():
        row = rs.get(src)
        if isinstance(row, dict):
            lat = row["latency_ms"]["median"]
            V[f"router.{key}.acc"] = fmt_pct(100 * row["acc"])
            V[f"router.{key}.hybrid"] = fmt_pct(100 * row["hybrid_recall"])
            V[f"router.{key}.lat"] = f"{lat:,.0f} ms" if lat >= 100 else f"{lat:.1f} ms"
        else:
            for x in ("acc", "hybrid", "lat"):
                V[f"router.{key}.{x}"] = f"not run ({row or 'absent from the saved file'})"
    for arm in "ABC":
        V[f"latency_med.{arm}"] = fmt_s(A[arm]["latency_median_s"] if arm in A else None)
        V[f"latency_p95.{arm}"] = fmt_s(A[arm]["latency_p95_s"] if arm in A else None)
        V[f"ptok.{arm}"] = fmt_int(A[arm]["prompt_tokens_median"] if arm in A else None)
    for c in CAUSES:
        for arm in "BC":
            V[f"err.{c}.{arm}"] = str(err_counts[arm][c])
    for arm in "BC":
        V[f"err_total.{arm}"] = str(sum(err_counts[arm].values()))
    for s in ("CB", "CA", "CB2"):
        p = M["paired"].get(s)
        if p:
            V[f"wins_{s}"], V[f"losses_{s}"], V[f"ties_{s}"] = str(p["wins"]), str(p["losses"]), str(p["ties"])
            V[f"p_{s}"] = f"{p['p_mcnemar_exact']:.4f}" + (" (fewer than 10 discordant pairs)" if p["small_discordant_note"] else "")
            V[f"ci_{s}"] = f"[{p['ci95_pts'][0]:+.1f}, {p['ci95_pts'][1]:+.1f}] pts"
        else:
            for x in ("wins", "losses", "ties", "p", "ci"):
                V[f"{x}_{s}"] = "not run (an arm is missing)"
    hw = hardware()
    V["review_date"] = date.today().isoformat()
    V["llm_tag"] = f"{manifest['model']['name']} {manifest['model']['quantization']}"
    V["hardware"] = f"{hw['gpu']}; {hw['platform']}; Python {hw['python']}"
    for k in ("n_total", "n_db", "n_syn", "n_trai", "n_cross", "n_core", "n_new", "n_docq"):
        V[k] = str(counts_q[k])
    V["n_router_test"] = str(M["router_saved"]["n"])
    V["n_oos"] = str(M["abstention_saved"]["n_should_abstain"])
    V["abst_prec"] = fmt_pct(100 * M["abstention_saved"]["precision"])
    V["abst_rec"] = fmt_pct(100 * M["abstention_saved"]["recall"])
    V["false_abst"] = fmt_pct(100 * M["abstention_saved"]["false_abstention_rate"])
    V["armB_components"] = "\n".join(["SQL retrieval (StructuredRetriever: exact filter / aggregate; msisdn guard)", "Document retrieval (MiniLM FAISS top-10, CrossEncoder rerank, top 5)",
                                      "Reciprocal Rank Fusion (k=60)", "Shared 6-block prompt limit", "Cited answers ([E#]); same model, decoding and prompts in every arm",
                                      "SciFact serving-time filter ON", "No answer cache", "No router, no semantic layer, no citation verification"])
    V["armC_components"] = "\n".join(["Everything in B2: per-source budget 5 database + 3 document blocks (chosen from the E14a failure analysis on the same 22 questions; never tuned)",
                                      "Semantic layer ON: ontology term normalisation (concept hint -> canonical terms in the FAISS query) + document-graph expansion (shared-concept bridges, gate weight)",
                                      "Router ON: auto chain Laya fine-tuned -> embedding -> rule decides which sources are searched",
                                      "Citation verification ON (project verifier, flags sentences, does not change the answer)", "SciFact serving-time filter ON", "No answer cache"])
    V["connected_list"] = "\n".join(["SQL retrieval (StructuredRetriever) feeds the E14 pipeline", "Document retrieval (FAISS + CrossEncoder) feeds the E14 pipeline",
                                     "Per-source context budget (RagConfig) in B2 and C", "Ontology concept hint and crosswalk category names used for query normalisation (arm C and the ontology ablation)",
                                     "Document graph shared-concept bridges (graph_expand) merged by weighted RRF (arm C and the docgraph ablation)",
                                     "QA router (Laya fine-tuned -> embedding -> rule) in arm C and the router ablation", "Citation verifier (QA layer) applied to B and C answers",
                                     "SciFact serving-time filter (all arms)"])
    V["not_connected_list"] = "\n".join(["Structured KG: present in the repo (QAConfig.use_structured_kg flag) but not read by any retrieval code", "RELATED_TO links: 0 of 84 resolve to an indexed document, so the explicit see-also hop is unusable",
                                         "Person B's parser-wordboundary branch: not merged (measured on the original substring parser)", "ColPali: not used in any arm",
                                         "Ontology on the SQL side (no cross-table traversal or entity linking)", "Router's decomposition step: not used (E14 prompts are single-shot)"])
    n_s = integ["n_sample"] if integ else None
    V["human_review_status"] = f"sample of {n_s} exported, not yet reviewed by a human" if n_s else "not run (integrity stage not executed)"
    un = counts_q.get("unreviewed_by_category", {})
    V["review_status_new"] = ("Unreviewed by a human: multi (%d questions written by Claude Code: MH01-05 and MH12-13); cross (%d questions: facts and document ids from Person B's frozen benchmark, "
                              "but the question prefix and the atomic fact split were written by Claude Code); db held-out (%d questions: ground truth computed from SQLite for Person B's structured benchmark). "
                              "The 22 core questions use the E14a gold." % (len(un.get("multi", [])), len(un.get("cross", [])), len(un.get("db", []))))
    rep = M.get("repro_E14a")
    if rep:
        V["repro_E14a"] = (f"B (SciFact filter off) on the original 22: {fmt_pct(rep['B_scifact_off_core22_mean'])} (runs {rep['B_scifact_off_core22_per_run']}) vs documented 79.5%. "
                           "Differences from E14a: 3 runs instead of 1 (decoding is not deterministic here); no cached answers (E14a reused 5 of its 22 RAG answers from an earlier subset run); "
                           "code and indexes as of commit 8e86ea9 (SciFact filter, msisdn guard and decomposer fix exist now); E14a recorded no package versions so the environment cannot be compared "
                           "(torch/transformers/sentence-transformers/faiss dist-info dates precede E14a). Same: model qwen2.5:7b-instruct Q4_K_M, temperature 0, seed 42, E14a prompts and judge, shared 6-block budget, same 22 questions.")
        off, on = rep["B_scifact_off_core22_mean"], rep["B_scifact_on_core22_mean"]
        r_off, r_on = rep["retrieval_off_core14"], rep["retrieval_on_core14"]
        V["scifact_effect"] = (f"On the 14 E14a document questions the old, SciFact-filtered and clean indexes return identical rankings (R@1 {cmp_['metrics']['old']['all_14']['R@1']:.4f}, MRR@10 "
                               f"{cmp_['metrics']['old']['all_14']['MRR@10']:.4f}; no SciFact chunk in any old top-10; docs/SCIFACT_INDEX_COMPARISON.md), and arm B on the original 22 scores "
                               f"{fmt_pct(off)} with the filter off versus {fmt_pct(on)} with it on ({fmt_delta(None if off is None or on is None else off - on)}; R@1 on the 14 document questions "
                               f"{fmt_ratio(r_off['R@1'])} vs {fmt_ratio(r_on['R@1'])}).")
    else:
        V["repro_E14a"] = V["scifact_effect"] = "not run (the SciFact-off reproduction arm has no results)"
    V["dangling_links"] = (f"{M['related_to']['resolving']} of {M['related_to']['edges']} RELATED_TO links resolve to an indexed document in the graph used by arm C "
                           "(knowledge_graph/output/graph.json, checked against the clean index); the corpus / related_ids fix for Person B's graph is not yet in.")
    return V


if __name__ == "__main__":
    main()
