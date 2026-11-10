"""
Report stage of the KG-hardening evaluation: raw_answers.jsonl + scored_answers.jsonl (+ the v3 results, read-only) -> every output under
results/kg_hardening_eval/: metrics.json, comparison_table.md, error_table.csv, per_question_scores.csv, graph_diagnostics.md (+ .json).

    .venv_colpali/Scripts/python.exe eval/kg_hardening_eval/run_report.py

Definitions are the v3 ones (eval/perf_report/run_report.py, imported and reused, not copied):
  * 3 runs per arm; percentages are the MEAN over runs of the per-run percentage, with the min-max range in metrics.json;
  * correctness % = mean(score)/2 over scorable answers (E14a: 0/1/2); "right" = score 2;
  * paired statistics compare per-question values; exact two-sided McNemar on the discordant pairs; paired bootstrap over QUESTIONS (10,000
    resamples, seed 20261031) of the per-question difference. Three scoring rules:
      strict   per-question value = share of runs fully correct (score 2); right = value > 0.5 (majority of runs)      [the v3 rule]
      partial  per-question value = mean(score)/2 over runs; win/loss = higher/lower value, tie = equal
      lenient  per-question value = share of runs with score >= 1; right = value > 0.5
  * error causes: the v3 deterministic rule (run_report.classify), one cause per answer with correctness < 2, with B2 of the same run as the
    reference record for the C arms; error counts are ANSWERS (3 runs x 42 questions per arm);
  * v3 arms B2 and C are loaded from results/perf_report/ (read-only) as "v3_B2" and "v3_C" for the parser-effect and drift lines.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_kg as k  # noqa: E402

h = k.h
import run_report as rr  # noqa: E402  (eval/perf_report/run_report.py; its RES/ARMS are taken from the patched harness at import)

from knowledge_graph.graph_augmented_retrieval import DEFAULT_BRIDGES, GRAPH_CANDIDATES, graph_expand, load_graph_index  # noqa: E402
from integration.rag.semantic_layer import GRAPH_JSON, _read_related_edges  # noqa: E402

RES = k.RES
ARMS = k.ARMS
REF_ARMS = ["v3_B2", "v3_C"]
RULES = ["strict", "partial", "lenient"]
COMPARISONS = [("C_V1", "C_V0"), ("C_V1_links", "C_V1"), ("C_V0", "B2"), ("C_V1", "B2"), ("C_V1_links", "B2"), ("B2", "v3_B2"), ("C_V0", "v3_C")]
RUNS = [1, 2, 3]
INDEX_META = k.ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore" / "chunk_metadata.json"


# ---------------------------------------------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------------------------------------------
def load():
    qs = {q["id"]: q for q in h.load_questions()}
    raw = {(r["arm"], r["id"], r["run"]): r for r in h.read_jsonl(k.RAW)}
    scored = {(s["arm"], s["id"], s["run"]): s for s in h.read_jsonl(k.SCORED)}
    for r in h.read_jsonl(k.V3_RAW):
        if r["arm"] in ("B2", "C"):
            raw[("v3_" + r["arm"], r["id"], r["run"])] = r
    for s in h.read_jsonl(k.V3_SCORED):
        if s["arm"] in ("B2", "C"):
            scored[("v3_" + s["arm"], s["id"], s["run"])] = s
    return qs, raw, scored


def runs_of(raw, arm):
    return sorted({key[2] for key in raw if key[0] == arm})


# ---------------------------------------------------------------------------------------------------------------------------------
# paired statistics under three rules
# ---------------------------------------------------------------------------------------------------------------------------------
def per_question_value(arm, qs, scored, runs, rule):
    out = {}
    for qid in qs:
        v = [scored[(arm, qid, r)]["correctness"] for r in runs if (arm, qid, r) in scored and scored[(arm, qid, r)]["correctness"] is not None]
        if not v:
            out[qid] = None
        elif rule == "strict":
            out[qid] = sum(1 for x in v if x == 2) / len(v)
        elif rule == "lenient":
            out[qid] = sum(1 for x in v if x >= 1) / len(v)
        else:
            out[qid] = sum(v) / (2 * len(v))
    return out


def paired_rule(a_arm, b_arm, qs, scored, runs, rule):
    """wins = a better than b on that question (strict/lenient: right in a majority of runs; partial: higher per-question mean)."""
    ra, rb = per_question_value(a_arm, qs, scored, runs, rule), per_question_value(b_arm, qs, scored, runs, rule)
    wins = losses = ties = 0
    diffs, win_ids, loss_ids = [], [], []
    for qid in qs:
        if ra[qid] is None or rb[qid] is None:
            continue
        diffs.append(ra[qid] - rb[qid])
        if rule == "partial":
            better, worse = ra[qid] > rb[qid] + 1e-9, rb[qid] > ra[qid] + 1e-9
        else:
            better, worse = (ra[qid] > 0.5) and not (rb[qid] > 0.5), (rb[qid] > 0.5) and not (ra[qid] > 0.5)
        if better:
            wins += 1; win_ids.append(qid)
        elif worse:
            losses += 1; loss_ids.append(qid)
        else:
            ties += 1
    return {"rule": rule, "a": a_arm, "b": b_arm, "wins": wins, "losses": losses, "ties": ties, "n_pairs": len(diffs), "discordant": wins + losses,
            "p_mcnemar_exact": round(rr.mcnemar_exact(wins, losses), 4), "fewer_than_10_discordant": (wins + losses) < 10,
            "ci95_pts": rr.bootstrap_ci(diffs) if diffs else None, "mean_diff_pts": round(100 * sum(diffs) / len(diffs), 1) if diffs else None,
            "win_ids": win_ids, "loss_ids": loss_ids}


# ---------------------------------------------------------------------------------------------------------------------------------
# per-arm block (v3 functions)
# ---------------------------------------------------------------------------------------------------------------------------------
def arm_block(arm, qs, raw, scored, runs, flagged):
    a = {"n_records": sum(1 for key in raw if key[0] == arm), "runs": runs}
    for subset in ["all", "core"] + rr.CATS:
        a[f"correctness.{subset}"] = rr.arm_metric(arm, subset, "correctness", scored, qs, runs)
    for field in ("relevance", "groundedness", "halluc_ref", "halluc_ctx"):
        a[field] = rr.arm_metric(arm, "all", field, scored, qs, runs)
        a[field + ".core"] = rr.arm_metric(arm, "core", field, scored, qs, runs)
    recs = [raw[key] for key in raw if key[0] == arm]
    lat = [raw[key]["latency_s"] for key in raw if key[0] == arm and key not in flagged]
    a["latency_records_excluded"] = sum(1 for key in raw if key[0] == arm and key in flagged)
    a["latency_exclusion_reasons"] = dict(Counter(flagged[key].split(":")[0] for key in raw if key[0] == arm and key in flagged))
    a["n_scored"] = sum(1 for key in scored if key[0] == arm)
    a["scored_runs"] = sorted({key[2] for key in scored if key[0] == arm})
    a["variability"] = rr.variability(arm, qs, raw, scored, runs)
    a["latency_median_s"] = round(statistics.median(lat), 2) if lat else None
    a["latency_p95_s"] = h.p95(lat)
    a["prompt_tokens_median"] = statistics.median([x["prompt_tokens"] for x in recs if x["prompt_tokens"]]) if any(x["prompt_tokens"] for x in recs) else None
    a["n_cached_records"] = sum(1 for x in recs if x.get("cached"))
    a["n_abstained"] = sum(1 for x in recs if x.get("abstained"))
    a["n_parse_errors_in_judge"] = sum(1 for key, s in scored.items() if key[0] == arm and s.get("judge_parse_error"))
    a["retrieval_docq"] = rr.retrieval_metrics(arm, qs, raw, runs)
    a["retrieval_core14"] = rr.retrieval_metrics(arm, qs, raw, runs, {q for q in qs if qs[q]["is_core"]})
    a["retrieval_deterministic_across_runs"] = not rr.retrieval_is_deterministic(arm, qs, raw, runs)
    a["db_rowcov"] = rr.db_rowcov(arm, qs, raw, runs)
    if any("citation" in s for key, s in scored.items() if key[0] == arm):
        per_run, totals = rr.citation_metrics(arm, scored, qs, runs)
        a["citation"] = {"per_run": per_run, "totals": totals}
    else:
        a["citation"] = None   # v3 B2 was not citation-checked
    routes = Counter((x.get("route") or {}).get("final") for x in recs if x.get("route"))
    a["routes"] = dict(routes) if routes else None
    a["router_errors"] = sum(1 for x in recs if (x.get("route") or {}).get("error"))
    sems = [x.get("semantic") or {} for x in recs if x.get("semantic") is not None]
    a["graph"] = {"records_with_added_chunks": sum(1 for s in sems if s.get("added_chunks")), "added_chunks_total_all_runs": sum(len(s.get("added_chunks") or []) for s in sems),
                  "records_with_graph_weight_positive": sum(1 for s in sems if (s.get("graph_weight") or 0) > 0),
                  "related_neighbours_added_all_runs": sum(s.get("related_neighbours_added") or 0 for s in sems)} if sems else None
    return a


# ---------------------------------------------------------------------------------------------------------------------------------
# error analysis (v3 rule)
# ---------------------------------------------------------------------------------------------------------------------------------
def error_analysis(qs, raw, scored):
    rows, counts = [], {a: {c: 0 for c in rr.CAUSES} for a in ARMS}
    for arm in ARMS:
        rule_arm = "C" if arm in k.C_ARMS else "B2"      # classify() keys its router/graph branches on the v3 arm names
        for r in RUNS:
            for qid, q in qs.items():
                key = (arm, qid, r)
                if key not in scored or scored[key]["correctness"] is None or scored[key]["correctness"] == 2:
                    continue
                ref = raw.get(("B2", qid, r)) if arm in k.C_ARMS else None
                cause, detail = rr.classify(rule_arm, q, raw[key], scored[key], ref, scored.get(("B2", qid, r)))
                counts[arm][cause] += 1
                rows.append({"arm": arm, "run": r, "id": qid, "category": q["category"], "correctness": scored[key]["correctness"], "cause": cause, "detail": detail})
    return rows, counts


# ---------------------------------------------------------------------------------------------------------------------------------
# graph diagnostics per C arm
# ---------------------------------------------------------------------------------------------------------------------------------
def graph_diagnostics(qs, raw):
    gi = load_graph_index(GRAPH_JSON)
    n_docs = gi.document_count
    hub_threshold = k.V1_OPTIONS["hub_fraction"] * n_docs
    related = {}
    for a, b in _read_related_edges(GRAPH_JSON):
        related.setdefault(a, set()).add(b); related.setdefault(b, set()).add(a)
    idx_docs = {m["document_id"] for m in json.loads(INDEX_META.read_text(encoding="utf-8"))}
    out = {"graph": {"document_count_N": n_docs, "hub_threshold_docs": hub_threshold, "related_pairs_resolvable_in_index": sum(1 for a, b in _read_related_edges(GRAPH_JSON) if a in idx_docs and b in idx_docs)},
           "note": "run 1 is used (retrieval determinism across runs is checked and reported per arm in metrics.json); 'relevant' = the added document is a gold document "
                   "of the question (the v3 rule); 'hub-only' = every bridge concept the added document shares with a seed has document frequency > hub_threshold "
                   "(the V1 hub cut would drop it); 'displaced' = a gold document in B2's top 10 (same run) that is not in this arm's top 10 while this arm did search documents.",
           "arms": {}}
    for arm in k.C_ARMS:
        opts = k.arm_settings(arm)["graph_expand_options"]
        rows, summ = [], {"questions": 0, "questions_doc_searched": 0, "questions_gate_positive": 0, "questions_with_added_chunks": 0, "added_chunks_total": 0,
                          "added_documents_total": 0, "added_via": Counter(), "added_relevant": 0, "added_relevant_questions": 0,
                          "docs_added_per_question": [], "displaced_questions": [], "gold_rank_1_B2": 0, "gold_rank_1_arm": 0, "doc_questions": 0,
                          "gold_rank_changes": {"better": 0, "same": 0, "worse": 0, "lost_from_top10": 0}, "link_docs_added_total": 0, "link_docs_in_top10": 0, "link_docs_in_prompt": 0}
        for qid, q in qs.items():
            rec, b2 = raw.get((arm, qid, 1)), raw.get(("B2", qid, 1))
            if rec is None or b2 is None:
                continue
            summ["questions"] += 1
            sem = rec.get("semantic") or {}
            seeds, gw = sem.get("seeds") or [], sem.get("graph_weight") or 0.0
            searched = bool(rec["doc_top10"])
            summ["questions_doc_searched"] += searched
            summ["questions_gate_positive"] += gw > 0
            gold = rr.doc_requirement(q)
            expanded = {x["document_id"]: x for x in graph_expand(seeds, gi, bridges=DEFAULT_BRIDGES, limit=GRAPH_CANDIDATES, **opts)} if seeds else {}
            prompt_docs = rr.prompt_doc_ids(rec)
            added, link_docs = [], set()
            for chunk in sem.get("added_chunks") or []:
                doc = chunk.rsplit("_chunk_", 1)[0]
                shared = expanded.get(doc, {}).get("shared_concepts", [])
                via_related = sorted(s for s in seeds if doc in related.get(s, set()))
                if via_related and not shared:
                    via = "RELATED_TO"
                    link_docs.add(doc)
                else:
                    dfs = {c: gi.document_frequency(*c.split(":", 1)) for c in shared}
                    via = "bridge concept (hub-only)" if shared and all(df > hub_threshold for df in dfs.values()) else "bridge concept (has a specific concept)"
                added.append({"chunk": chunk, "document_id": doc, "via": via, "shared_concepts": shared, "concept_df": dfs if via != "RELATED_TO" else {},
                              "related_from_seeds": via_related, "relevant": doc in gold, "in_prompt": doc in prompt_docs, "rank_in_top10": next((i for i, d in enumerate(rec["doc_top10"], 1) if d == doc), None)})
                summ["added_via"][via] += 1
            n_added_docs = len({a_["document_id"] for a_ in added})
            if added:
                summ["questions_with_added_chunks"] += 1
                summ["added_chunks_total"] += len(added)
                summ["added_documents_total"] += n_added_docs
                summ["docs_added_per_question"].append(n_added_docs)
                rel = sum(1 for a_ in added if a_["relevant"])
                summ["added_relevant"] += rel
                summ["added_relevant_questions"] += rel > 0
            summ["link_docs_added_total"] += sem.get("related_neighbours_added") or 0
            summ["link_docs_in_top10"] += sum(1 for d in link_docs if d in rec["doc_top10"])
            summ["link_docs_in_prompt"] += sum(1 for d in link_docs if d in prompt_docs)
            rank_b2 = next((i for i, d in enumerate(b2["doc_top10"], 1) if d in gold), None) if gold else None
            rank_arm = next((i for i, d in enumerate(rec["doc_top10"], 1) if d in gold), None) if gold else None
            displaced = bool(gold) and searched and rank_b2 is not None and rank_arm is None
            if gold:
                summ["doc_questions"] += 1
                summ["gold_rank_1_B2"] += rank_b2 == 1
                summ["gold_rank_1_arm"] += rank_arm == 1
                if searched and rank_b2 is not None:
                    if rank_arm is None:
                        summ["gold_rank_changes"]["lost_from_top10"] += 1
                    elif rank_arm < rank_b2:
                        summ["gold_rank_changes"]["better"] += 1
                    elif rank_arm == rank_b2:
                        summ["gold_rank_changes"]["same"] += 1
                    else:
                        summ["gold_rank_changes"]["worse"] += 1
            if displaced:
                summ["displaced_questions"].append(qid)
            rows.append({"id": qid, "category": q["category"], "route": (rec.get("route") or {}).get("final"), "graph_weight": gw, "concept": sem.get("concept"),
                         "seeds": seeds, "n_neighbour_docs": len(sem.get("neighbour_docs") or []), "n_added_chunks": len(added), "n_added_documents": n_added_docs,
                         "related_neighbours_added": sem.get("related_neighbours_added"), "gold_documents": gold, "gold_rank_B2": rank_b2, "gold_rank_arm": rank_arm,
                         "displaced_from_top10": displaced, "arm_top3": rec["doc_top10"][:3], "B2_top3": b2["doc_top10"][:3], "prompt_docs": prompt_docs, "added": added})
        d = summ["docs_added_per_question"]
        summ["docs_added_per_question"] = {"mean": round(sum(d) / len(d), 2) if d else None, "max": max(d) if d else None, "n": len(d)}
        summ["added_via"] = dict(summ["added_via"])
        out["arms"][arm] = {"graph_expand_options": opts, "use_related_links": k.arm_settings(arm)["use_related_links"], "summary": summ, "rows": rows}
    return out


# ---------------------------------------------------------------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------------------------------------------------------------
def fp(x):
    return rr.fmt_pct(x)


def mean_(xs):
    return rr.mean(xs)


def comparison_table(M, err_counts, G) -> str:
    cols = ["v3_B2", "B2", "C_V0", "C_V1", "C_V1_links", "v3_C"]
    A = M["arms"]

    def cell(arm, f):
        a = A.get(arm)
        if not a:
            return "n/a"
        try:
            return f(a)
        except (KeyError, TypeError):
            return "n/a"

    def pct_row(key):
        return lambda a: fp(mean_(a[key])) + (f" (range {rr.rng(a[key])[0]:.1f}-{rr.rng(a[key])[1]:.1f})" if rr.rng(a[key]) and rr.rng(a[key])[0] != rr.rng(a[key])[1] else "")

    lines = ["# KG-hardening evaluation: comparison table", "",
             "All 42 questions, 3 runs per arm; percentages are the mean over runs (min-max range when the runs differ). v3_B2 and v3_C are the v3 report's arms "
             "(results/perf_report/, read-only), shown for the parser-effect and drift lines only. 'not scored' = that metric was not judged for that arm.", "",
             "## Headline and judge metrics", "", "| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    rows = [("correctness, all 42 (partial credit)", pct_row("correctness.all")), ("correctness, core 22", pct_row("correctness.core")),
            ("relevance", pct_row("relevance")), ("groundedness", pct_row("groundedness")),
            ("hallucination vs reference evidence", pct_row("halluc_ref")), ("hallucination vs retrieved context", pct_row("halluc_ctx"))]
    for name, f in rows:
        lines.append(f"| {name} | " + " | ".join(("not scored" if (arm == "v3_B2" and name in ("relevance", "hallucination vs reference evidence")) else cell(arm, f)) for arm in cols) + " |")
    for name, key in (("citation coverage", "cov"), ("citation correctness", "correct"), ("unsupported-claim rate", "unsup")):
        lines.append(f"| {name} | " + " | ".join(("not scored" if not A.get(arm, {}).get("citation") else fp(mean_(A[arm]["citation"]["per_run"][key]))) if arm in A else "n/a" for arm in cols) + " |")
    lines += ["", "## Per-category correctness (partial credit)", "", "| category (n) | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for c in rr.CATS:
        n = sum(1 for q in M["questions"].values() if q["category"] == c)
        lines.append(f"| {c} ({n}) | " + " | ".join(cell(arm, pct_row(f"correctness.{c}")) for arm in cols) + " |")
    lines += ["", "## Retrieval (25 document questions, run 1; identical across runs unless stated) and database-row coverage", "",
              "| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for key in ("R@1", "R@3", "R@5", "R@10", "MRR@10"):
        lines.append(f"| {key} | " + " | ".join(cell(arm, lambda a, key=key: rr.fmt_ratio(a["retrieval_docq"][key])) for arm in cols) + " |")
    lines.append("| retrieval identical across runs | " + " | ".join(cell(arm, lambda a: str(a["retrieval_deterministic_across_runs"])) for arm in cols) + " |")
    lines.append("| database-row coverage | " + " | ".join(cell(arm, pct_row("db_rowcov")) for arm in cols) + " |")
    lines += ["", "## Latency, prompt size, abstentions, routing", "", "| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    lines.append("| latency median | " + " | ".join(cell(arm, lambda a: rr.fmt_s(a["latency_median_s"])) for arm in cols) + " |")
    lines.append("| latency p95 | " + " | ".join(cell(arm, lambda a: rr.fmt_s(a["latency_p95_s"])) for arm in cols) + " |")
    lines.append("| latency records excluded (gap/slow) | " + " | ".join(cell(arm, lambda a: str(a["latency_records_excluded"])) for arm in cols) + " |")
    lines.append("| prompt tokens median | " + " | ".join(cell(arm, lambda a: rr.fmt_int(a["prompt_tokens_median"])) for arm in cols) + " |")
    lines.append("| abstentions (records) | " + " | ".join(cell(arm, lambda a: str(a["n_abstained"])) for arm in cols) + " |")
    lines.append("| routes (final) | " + " | ".join(cell(arm, lambda a: json.dumps(a["routes"]) if a["routes"] else "no router") for arm in cols) + " |")
    lines.append("| router errors | " + " | ".join(cell(arm, lambda a: str(a["router_errors"])) for arm in cols) + " |")
    lines += ["", "## Run-to-run variability", "", "| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    lines.append("| questions with identical correctness in all runs | " + " | ".join(cell(arm, lambda a: f"{a['variability']['identical_correctness']}/{a['variability']['questions_compared_correctness']} ({a['variability']['identical_correctness_pct']}%)") for arm in cols) + " |")
    lines.append("| questions with identical answer text in all runs | " + " | ".join(cell(arm, lambda a: f"{a['variability']['identical_answer_text']}/{a['variability']['questions_compared_text']} ({a['variability']['identical_answer_text_pct']}%)") for arm in cols) + " |")
    lines.append("| correctness per run | " + " | ".join(cell(arm, lambda a: json.dumps(a["correctness.all"])) for arm in cols) + " |")
    lines += ["", "## Error causes (answers with correctness < 2; v3 rule, B2 of the same run as reference for the C arms)", "",
              "| cause | " + " | ".join(ARMS) + " |", "|---|" + "---|" * len(ARMS)]
    for c in rr.CAUSES:
        lines.append(f"| {c} | " + " | ".join(str(err_counts[a][c]) for a in ARMS) + " |")
    lines.append("| total | " + " | ".join(str(sum(err_counts[a].values())) for a in ARMS) + " |")
    lines += ["", "## Graph diagnostics (run 1; see graph_diagnostics.md)", "", "| item | " + " | ".join(k.C_ARMS) + " |", "|---|" + "---|" * len(k.C_ARMS)]
    gs = {a: G["arms"][a]["summary"] for a in k.C_ARMS}
    for name, f in (("questions with chunks added", lambda s: str(s["questions_with_added_chunks"])), ("chunks added (total)", lambda s: str(s["added_chunks_total"])),
                    ("documents added (total)", lambda s: str(s["added_documents_total"])), ("documents added per question (mean / max)", lambda s: f"{s['docs_added_per_question']['mean']} / {s['docs_added_per_question']['max']}"),
                    ("added via RELATED_TO link", lambda s: str(s["added_via"].get("RELATED_TO", 0))), ("added via bridge concept, hub-only", lambda s: str(s["added_via"].get("bridge concept (hub-only)", 0))),
                    ("added via bridge concept, has a specific concept", lambda s: str(s["added_via"].get("bridge concept (has a specific concept)", 0))),
                    ("added chunks relevant to the gold evidence", lambda s: f"{s['added_relevant']} of {s['added_chunks_total']}"),
                    ("questions where graph chunks displaced the gold document from the top 10", lambda s: f"{len(s['displaced_questions'])} {s['displaced_questions']}"),
                    ("gold at rank 1 (B2 / this arm), 25 doc questions", lambda s: f"{s['gold_rank_1_B2']} / {s['gold_rank_1_arm']}"),
                    ("gold rank vs B2 (better / same / worse / lost)", lambda s: f"{s['gold_rank_changes']['better']} / {s['gold_rank_changes']['same']} / {s['gold_rank_changes']['worse']} / {s['gold_rank_changes']['lost_from_top10']}"),
                    ("RELATED_TO documents appended by the layer (run 1)", lambda s: str(s["link_docs_added_total"]))):
        lines.append(f"| {name} | " + " | ".join(f(gs[a]) for a in k.C_ARMS) + " |")
    lines += ["", "## Paired comparisons (question level, 42 pairs; exact McNemar two-sided; paired bootstrap 95% CI in points of the per-question value)", ""]
    for rule in RULES:
        lines += [f"### Rule: {rule}", "", "| comparison | wins | losses | ties | McNemar p | 95% CI (pts) | mean diff (pts) | note |", "|---|---|---|---|---|---|---|---|"]
        for a, b in COMPARISONS:
            p = M["paired"].get(f"{a}_vs_{b}", {}).get(rule)
            if not p:
                lines.append(f"| {a} vs {b} | n/a | n/a | n/a | n/a | n/a | n/a | an arm is missing |")
                continue
            lines.append(f"| {a} vs {b} | {p['wins']} | {p['losses']} | {p['ties']} | {p['p_mcnemar_exact']:.4f} | [{p['ci95_pts'][0]:+.1f}, {p['ci95_pts'][1]:+.1f}] | {p['mean_diff_pts']:+.1f} | "
                         f"{'fewer than 10 discordant pairs (low power)' if p['fewer_than_10_discordant'] else ''} wins {p['win_ids']} losses {p['loss_ids']} |")
        lines.append("")
    return "\n".join(lines)


def graph_markdown(G) -> str:
    lines = ["# Graph diagnostics per C arm (run 1)", "", G["note"], "", f"Graph: N = {G['graph']['document_count_N']} documents with concept edges; V1 hub threshold = {G['graph']['hub_threshold_docs']} documents; "
             f"RELATED_TO pairs resolvable in the index: {G['graph']['related_pairs_resolvable_in_index']}.", ""]
    for arm, g in G["arms"].items():
        s = g["summary"]
        lines += [f"## {arm}  (graph_expand options {g['graph_expand_options']}, use_related_links={g['use_related_links']})", "",
                  f"* questions: {s['questions']}; documents searched (route unstructured/hybrid): {s['questions_doc_searched']}; gate weight > 0: {s['questions_gate_positive']}",
                  f"* questions with chunks added: {s['questions_with_added_chunks']}; chunks added: {s['added_chunks_total']}; documents added: {s['added_documents_total']} "
                  f"(per question mean {s['docs_added_per_question']['mean']}, max {s['docs_added_per_question']['max']})",
                  f"* added via: {s['added_via']}",
                  f"* added chunks relevant to the gold evidence: {s['added_relevant']} of {s['added_chunks_total']} (in {s['added_relevant_questions']} questions)",
                  f"* RELATED_TO documents appended by the layer: {s['link_docs_added_total']}; of the RELATED_TO-only added documents, in the top 10: {s['link_docs_in_top10']}, in the prompt: {s['link_docs_in_prompt']}",
                  f"* gold document at rank 1 on the {s['doc_questions']} document questions: B2 {s['gold_rank_1_B2']}, {arm} {s['gold_rank_1_arm']}; "
                  f"rank vs B2 (where B2 had it in the top 10 and this arm searched documents): {s['gold_rank_changes']}",
                  f"* questions where graph chunks displaced the gold document from the top 10: {s['displaced_questions'] or 'none'}", "",
                  "| id | cat | route | gw | concept | added chunks | added docs | links added | gold rank B2 -> arm | displaced | added (doc: via, relevant, in prompt) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in g["rows"]:
            if not r["n_added_chunks"] and not r["displaced_from_top10"]:
                continue
            added = "; ".join(f"{a['document_id']}: {a['via']}{', RELEVANT' if a['relevant'] else ''}{', in prompt' if a['in_prompt'] else ''}" for a in r["added"])
            lines.append(f"| {r['id']} | {r['category']} | {r['route']} | {r['graph_weight']} | {r['concept']} | {r['n_added_chunks']} | {r['n_added_documents']} | {r['related_neighbours_added']} | "
                         f"{r['gold_rank_B2']} -> {r['gold_rank_arm']} | {'YES' if r['displaced_from_top10'] else ''} | {added} |")
        lines.append("")
    return "\n".join(lines)


def per_question_csv(qs, raw, scored, path):
    cols = ARMS + REF_ARMS
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        head = ["id", "category", "is_core"]
        for a in cols:
            head += [f"{a}_run1", f"{a}_run2", f"{a}_run3", f"{a}_mean_pct"]
        for a in k.C_ARMS:
            head += [f"{a}_route", f"{a}_graph_weight", f"{a}_added_chunks_run1"]
        w.writerow(head)
        for qid, q in qs.items():
            row = [qid, q["category"], q["is_core"]]
            for a in cols:
                v = [scored.get((a, qid, r), {}).get("correctness") for r in RUNS]
                vv = [x for x in v if x is not None]
                row += [("" if x is None else x) for x in v] + [round(100 * sum(vv) / (2 * len(vv)), 1) if vv else ""]
            for a in k.C_ARMS:
                rec = raw.get((a, qid, 1)) or {}
                row += [(rec.get("route") or {}).get("final", ""), (rec.get("semantic") or {}).get("graph_weight", ""), len((rec.get("semantic") or {}).get("added_chunks") or [])]
            w.writerow(row)


# ---------------------------------------------------------------------------------------------------------------------------------
def main() -> None:
    qs, raw, scored = load()
    missing = [key for key in raw if key[0] in ARMS and key not in scored]
    if missing:
        print(f"WARNING: {len(missing)} raw records are not scored yet (report is partial)")
    flagged = h.flag_latency_records([raw[key] for key in sorted(raw, key=lambda key: raw[key].get("timestamp_utc") or "") if key[0] in ARMS])
    manifest = json.loads((RES / "run_manifest.json").read_text(encoding="utf-8")) if (RES / "run_manifest.json").exists() else None
    M = {"definitions": __doc__, "manifest_git_commit": (manifest or {}).get("git", {}).get("commit"), "questions": {q: {"category": qs[q]["category"], "is_core": qs[q]["is_core"]} for q in qs},
         "runs_per_arm": {a: len(runs_of(raw, a)) for a in ARMS + REF_ARMS}, "arms": {}}
    for arm in ARMS + REF_ARMS:
        runs = runs_of(raw, arm)
        if runs:
            M["arms"][arm] = arm_block(arm, qs, raw, scored, runs, flagged if arm in ARMS else {})
    M["paired"] = {}
    for a, b in COMPARISONS:
        if runs_of(raw, a) and runs_of(raw, b):
            M["paired"][f"{a}_vs_{b}"] = {rule: paired_rule(a, b, qs, scored, RUNS, rule) for rule in RULES}
    err_rows, err_counts = error_analysis(qs, raw, scored)
    M["error_analysis"] = {"counts": err_counts, "totals": {a: sum(c.values()) for a, c in err_counts.items()}}
    with open(RES / "error_table.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["arm", "run", "id", "category", "correctness", "cause", "detail"])
        w.writeheader(); w.writerows(err_rows)
    G = graph_diagnostics(qs, raw)
    M["graph_diagnostics_summary"] = {a: G["arms"][a]["summary"] for a in G["arms"]}
    M["parser_effect_B2_new_vs_v3"] = {"correctness_all_new": mean_(M["arms"]["B2"]["correctness.all"]) if "B2" in M["arms"] else None,
                                        "correctness_all_v3": mean_(M["arms"]["v3_B2"]["correctness.all"]) if "v3_B2" in M["arms"] else None,
                                        "paired": M["paired"].get("B2_vs_v3_B2"), "reading": "parser effect plus run-to-run noise; not a graph effect"}
    M["drift_check_C_V0_vs_v3_C"] = {"correctness_all_new": mean_(M["arms"]["C_V0"]["correctness.all"]) if "C_V0" in M["arms"] else None,
                                      "correctness_all_v3": mean_(M["arms"]["v3_C"]["correctness.all"]) if "v3_C" in M["arms"] else None,
                                      "paired": M["paired"].get("C_V0_vs_v3_C")}
    (RES / "graph_diagnostics.json").write_text(json.dumps(G, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (RES / "graph_diagnostics.md").write_text(graph_markdown(G), encoding="utf-8")
    (RES / "metrics.json").write_text(json.dumps(M, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (RES / "comparison_table.md").write_text(comparison_table(M, err_counts, G), encoding="utf-8")
    per_question_csv(qs, raw, scored, RES / "per_question_scores.csv")
    print(comparison_table(M, err_counts, G))
    print("written: metrics.json, comparison_table.md, error_table.csv, per_question_scores.csv, graph_diagnostics.md, graph_diagnostics.json")


if __name__ == "__main__":
    main()
