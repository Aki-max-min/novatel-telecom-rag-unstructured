"""
Report stage (both experiments; selected by FA_EXPERIMENT): raw_answers.jsonl + scored_answers.jsonl of the generated arms + the reused arms from
results/kg_hardening_eval/ -> every output under results/<experiment>/:
  metrics.json, values.json (one flat key per number), comparison_table.md, paired_comparisons.md, ablation_table.md (final_ablation only),
  graph_diagnostics.md (+ .json), error_table.csv, per_question_scores.csv.

    FA_EXPERIMENT=final_ablation  .venv_colpali/Scripts/python.exe eval/final_ablation/fa_report.py
    FA_EXPERIMENT=graph_merge_fix .venv_colpali/Scripts/python.exe eval/final_ablation/fa_report.py

Definitions are the v3 ones (eval/perf_report/run_report.py, imported and reused):
  * 3 runs per arm; percentages are the MEAN over runs of the per-run percentage (min-max range in metrics.json);
  * correctness (partial credit) = mean(score)/2 over scorable answers (E14a: 0/1/2); strict = share of questions fully correct (score 2) in a
    majority of runs; lenient = share of questions with score >= 1 in a majority of runs;
  * paired statistics compare per-question values under the three rules; exact two-sided McNemar on the discordant pairs; paired bootstrap over
    QUESTIONS (10,000 resamples, seed 20261031) of the per-question difference;
  * error causes: the v3 deterministic rule run_report.classify, one cause per answer with correctness < 2; the rule's arm key is "router" for R,
    "ontology" for O, "docgraph" for the graph-only arms, "C" for the C arms, "B" / "B2" for the baselines; reference record = B2 of the same run for
    router / layer arms; A is not classified (no retrieval: every cause but "model" is meaningless);
  * "n/a" wherever a metric cannot exist (A: groundedness, hallucination vs context, citations, retrieval, row coverage).
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_fa as fa  # noqa: E402

h = fa.h
import run_report as rr  # noqa: E402  (eval/perf_report/run_report.py)

from integration.rag.semantic_layer import GRAPH_JSON, _read_related_edges  # noqa: E402
from knowledge_graph.graph_augmented_retrieval import DEFAULT_BRIDGES, GRAPH_CANDIDATES, graph_expand, load_graph_index  # noqa: E402

RES = fa.RES
ARMS = fa.ARMS_ALL
RULES = ["strict", "partial", "lenient"]
RUNS = [1, 2, 3]
INDEX_META = fa.ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore" / "chunk_metadata.json"
RULE_ARM = {"A": None, "B": "B", "B2": "B2", "R": "router", "O": "ontology", "G0": "docgraph", "G1": "docgraph", "G1L": "docgraph", "GF": "docgraph",
            "GFL": "docgraph", "C_V0": "C", "C_V1": "C", "C_V1_links": "C"}
REF_B2 = {"R", "O", "G0", "G1", "G1L", "GF", "GFL", "C_V0", "C_V1", "C_V1_links"}
ABLATION_ROWS = [("B", "B", "E14a configuration: shared 6-block budget"), ("budget", "B2", "B + per-source budget 5 db + 3 doc"),
                 ("router", "R", "B2 + router"), ("ontology", "O", "B2 + ontology term normalisation only"),
                 ("graph legacy", "G0", "B2 + legacy document-graph expansion only (old merge)"), ("graph hardened", "G1", "B2 + hardened graph expansion only (old merge)"),
                 ("graph hardened + links", "G1L", "G1 + RELATED_TO hop (old merge)"), ("structured KG", None, "B2 + structured KG"),
                 ("C legacy", "C_V0", "B2 + router + full semantic layer, legacy graph (old merge)"), ("C hardened", "C_V1", "C_V0 with the hardened graph (old merge)"),
                 ("C hardened + links", "C_V1_links", "C_V1 + RELATED_TO hop (old merge)")]


# ---------------------------------------------------------------------------------------------------------------------------------
def load():
    qs = {q["id"]: q for q in h.load_questions()}
    raw, scored = fa.load_reused(check_counts=True)
    for r in h.read_jsonl(fa.RAW):
        raw[(r["arm"], r["id"], r["run"])] = r
    for s in h.read_jsonl(fa.SCORED) if fa.SCORED.exists() else []:
        scored[(s["arm"], s["id"], s["run"])] = s
    return qs, raw, scored


def runs_of(raw, arm):
    return sorted({key[2] for key in raw if key[0] == arm})


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


def majority_rate(arm, qs, scored, runs, rule):
    v = [x for x in per_question_value(arm, qs, scored, runs, rule).values() if x is not None]
    return round(100 * sum(1 for x in v if x > 0.5) / len(v), 1) if v else None


def arm_block(arm, qs, raw, scored, runs, flagged):
    a = {"n_records": sum(1 for key in raw if key[0] == arm), "runs": runs, "generated_here": arm in fa.ARMS_NEW}
    for subset in ["all", "core"] + rr.CATS:
        a[f"correctness.{subset}"] = rr.arm_metric(arm, subset, "correctness", scored, qs, runs)
    a["correctness_strict_pct"] = majority_rate(arm, qs, scored, runs, "strict")
    a["correctness_lenient_pct"] = majority_rate(arm, qs, scored, runs, "lenient")
    for field in ("relevance", "groundedness", "halluc_ref", "halluc_ctx"):
        a[field] = rr.arm_metric(arm, "all", field, scored, qs, runs)
        a[field + ".core"] = rr.arm_metric(arm, "core", field, scored, qs, runs)
    recs = [raw[key] for key in raw if key[0] == arm]
    lat = [raw[key]["latency_s"] for key in raw if key[0] == arm and key not in flagged]
    a["latency_records_excluded"] = sum(1 for key in raw if key[0] == arm and key in flagged)
    a["n_scored"] = sum(1 for key in scored if key[0] == arm)
    a["scored_runs"] = sorted({key[2] for key in scored if key[0] == arm})
    a["variability"] = rr.variability(arm, qs, raw, scored, runs)
    a["latency_median_s"] = round(statistics.median(lat), 2) if lat else None
    a["latency_p95_s"] = h.p95(lat)
    a["prompt_tokens_median"] = statistics.median([x["prompt_tokens"] for x in recs if x["prompt_tokens"]]) if any(x["prompt_tokens"] for x in recs) else None
    a["n_cached_records"] = sum(1 for x in recs if x.get("cached"))
    a["n_abstained"] = sum(1 for x in recs if x.get("abstained"))
    a["n_parse_errors_in_judge"] = sum(1 for key, s in scored.items() if key[0] == arm and s.get("judge_parse_error"))
    if arm == "A":
        a["retrieval_docq"] = a["retrieval_core14"] = a["db_rowcov"] = a["citation"] = None
        a["retrieval_deterministic_across_runs"] = None
    else:
        a["retrieval_docq"] = rr.retrieval_metrics(arm, qs, raw, runs)
        a["retrieval_core14"] = rr.retrieval_metrics(arm, qs, raw, runs, {q for q in qs if qs[q]["is_core"]})
        a["retrieval_deterministic_across_runs"] = not rr.retrieval_is_deterministic(arm, qs, raw, runs)
        a["db_rowcov"] = rr.db_rowcov(arm, qs, raw, runs)
        if any((s.get("citation") or {}).get("checked") for key, s in scored.items() if key[0] == arm):
            per_run, totals = rr.citation_metrics(arm, scored, qs, runs)
            a["citation"] = {"per_run": per_run, "totals": totals}
        else:
            a["citation"] = None
    routes = Counter((x.get("route") or {}).get("final") for x in recs if x.get("route"))
    a["routes"] = dict(routes) if routes else None
    a["router_errors"] = sum(1 for x in recs if (x.get("route") or {}).get("error"))
    sems = [x.get("semantic") or {} for x in recs if x.get("semantic") is not None]
    a["graph"] = {"records_with_added_chunks": sum(1 for s in sems if s.get("added_chunks")), "added_chunks_total_all_runs": sum(len(s.get("added_chunks") or []) for s in sems),
                  "records_with_graph_weight_positive": sum(1 for s in sems if (s.get("graph_weight") or 0) > 0),
                  "related_neighbours_added_all_runs": sum(s.get("related_neighbours_added") or 0 for s in sems)} if sems else None
    return a


# ---------------------------------------------------------------------------------------------------------------------------------
def error_analysis(qs, raw, scored):
    rows, counts = [], {}
    for arm in ARMS:
        rule_arm = RULE_ARM[arm]
        if rule_arm is None or not any(key[0] == arm for key in scored):
            continue
        counts[arm] = {c: 0 for c in rr.CAUSES}
        for r in RUNS:
            for qid, q in qs.items():
                key = (arm, qid, r)
                if key not in scored or scored[key]["correctness"] is None or scored[key]["correctness"] == 2:
                    continue
                ref = raw.get(("B2", qid, r)) if arm in REF_B2 else None
                cause, detail = rr.classify(rule_arm, q, raw[key], scored[key], ref, scored.get(("B2", qid, r)) if ref else None)
                if rule_arm in ("B", "B2") and cause in ("router", "graph"):
                    cause = "model"
                counts[arm][cause] += 1
                rows.append({"arm": arm, "run": r, "id": qid, "category": q["category"], "correctness": scored[key]["correctness"], "cause": cause, "detail": detail})
    return rows, counts


# ---------------------------------------------------------------------------------------------------------------------------------
def graph_diagnostics(qs, raw):
    arms = [a for a in fa.GRAPH_ARMS if any(key[0] == a for key in raw)]
    gi = load_graph_index(GRAPH_JSON)
    n_docs = gi.document_count
    hub_threshold = fa.V1_OPTIONS["hub_fraction"] * n_docs
    related = {}
    for a, b in _read_related_edges(GRAPH_JSON):
        related.setdefault(a, set()).add(b); related.setdefault(b, set()).add(a)
    idx_docs = {m["document_id"] for m in json.loads(INDEX_META.read_text(encoding="utf-8"))}
    out = {"graph": {"document_count_N": n_docs, "hub_threshold_docs": hub_threshold, "related_pairs_resolvable_in_index": sum(1 for a, b in _read_related_edges(GRAPH_JSON) if a in idx_docs and b in idx_docs)},
           "note": "run 1 is used (retrieval determinism across runs is checked per arm in metrics.json); 'relevant' = the added document is a gold document of the question "
                   "(the v3 rule); 'hub-only' = every bridge concept the added document shares with a seed has document frequency > hub_threshold (the V1 hub cut would drop it); "
                   "'displaced' = a gold document in B2's top 10 (same run) that is not in this arm's top 10 while this arm did search documents. Reference arm: B2.",
           "arms": {}}
    for arm in arms:
        opts = fa.arm_settings(arm)["graph_expand_options"]
        rows, summ = [], {"questions": 0, "questions_doc_searched": 0, "questions_gate_positive": 0, "questions_with_added_chunks": 0, "added_chunks_total": 0,
                          "added_documents_total": 0, "added_via": Counter(), "added_relevant": 0, "added_relevant_questions": 0, "added_in_prompt": 0,
                          "docs_added_per_question": [], "displaced_questions": [], "gold_rank_1_B2": 0, "gold_rank_1_arm": 0, "doc_questions": 0,
                          "gold_rank_changes": {"better": 0, "same": 0, "worse": 0, "lost_from_top10": 0}, "gold_rank_worse_or_lost_questions": [],
                          "link_docs_added_total": 0, "link_docs_in_top10": 0, "link_docs_in_prompt": 0}
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
                    dfs = {}
                else:
                    dfs = {c: gi.document_frequency(*c.split(":", 1)) for c in shared}
                    via = "bridge concept (hub-only)" if shared and all(df > hub_threshold for df in dfs.values()) else "bridge concept (has a specific concept)"
                added.append({"chunk": chunk, "document_id": doc, "via": via, "shared_concepts": shared, "concept_df": dfs, "related_from_seeds": via_related,
                              "relevant": doc in gold, "in_prompt": doc in prompt_docs, "rank_in_top10": next((i for i, d in enumerate(rec["doc_top10"], 1) if d == doc), None)})
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
                summ["added_in_prompt"] += sum(1 for a_ in added if a_["in_prompt"])
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
                        summ["gold_rank_changes"]["lost_from_top10"] += 1; summ["gold_rank_worse_or_lost_questions"].append(qid)
                    elif rank_arm < rank_b2:
                        summ["gold_rank_changes"]["better"] += 1
                    elif rank_arm == rank_b2:
                        summ["gold_rank_changes"]["same"] += 1
                    else:
                        summ["gold_rank_changes"]["worse"] += 1; summ["gold_rank_worse_or_lost_questions"].append(qid)
            if displaced:
                summ["displaced_questions"].append(qid)
            rows.append({"id": qid, "category": q["category"], "route": (rec.get("route") or {}).get("final"), "graph_weight": gw, "concept": sem.get("concept"),
                         "seeds": seeds, "n_neighbour_docs": len(sem.get("neighbour_docs") or []), "n_added_chunks": len(added), "n_added_documents": n_added_docs,
                         "related_neighbours_added": sem.get("related_neighbours_added"), "gold_documents": gold, "gold_rank_B2": rank_b2, "gold_rank_arm": rank_arm,
                         "displaced_from_top10": displaced, "arm_top3": rec["doc_top10"][:3], "B2_top3": b2["doc_top10"][:3], "prompt_docs": prompt_docs, "added": added})
        d = summ["docs_added_per_question"]
        summ["docs_added_per_question"] = {"mean": round(sum(d) / len(d), 2) if d else None, "max": max(d) if d else None, "n": len(d)}
        summ["added_via"] = dict(summ["added_via"])
        out["arms"][arm] = {"graph_expand_options": opts, "use_related_links": fa.arm_settings(arm)["use_related_links"], "summary": summ, "rows": rows}
    return out


def graph_markdown(G) -> str:
    lines = ["# Graph diagnostics per graph arm (run 1; reference arm B2)", "", G["note"], "",
             f"Graph: N = {G['graph']['document_count_N']} documents with concept edges; V1 hub threshold = {G['graph']['hub_threshold_docs']} documents; "
             f"RELATED_TO pairs resolvable in the index: {G['graph']['related_pairs_resolvable_in_index']}.", ""]
    for arm, g in G["arms"].items():
        s = g["summary"]
        lines += [f"## {arm}  (graph_expand options {g['graph_expand_options']}, use_related_links={g['use_related_links']})", "",
                  f"* questions: {s['questions']}; documents searched: {s['questions_doc_searched']}; gate weight > 0: {s['questions_gate_positive']}",
                  f"* questions with chunks added: {s['questions_with_added_chunks']}; chunks added: {s['added_chunks_total']}; documents added: {s['added_documents_total']} "
                  f"(per question mean {s['docs_added_per_question']['mean']}, max {s['docs_added_per_question']['max']}); added chunks that reached the prompt: {s['added_in_prompt']}",
                  f"* added via: {s['added_via']}",
                  f"* added chunks relevant to the gold evidence (gold document): {s['added_relevant']} of {s['added_chunks_total']} (in {s['added_relevant_questions']} questions)",
                  f"* RELATED_TO documents appended by the layer: {s['link_docs_added_total']}; of the RELATED_TO-only added documents, in the top 10: {s['link_docs_in_top10']}, in the prompt: {s['link_docs_in_prompt']}",
                  f"* gold document at rank 1 on the {s['doc_questions']} document questions: B2 {s['gold_rank_1_B2']}, {arm} {s['gold_rank_1_arm']}; "
                  f"rank vs B2 (where B2 had it in the top 10 and this arm searched documents): {s['gold_rank_changes']}; worse or lost on: {s['gold_rank_worse_or_lost_questions'] or 'none'}",
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


# ---------------------------------------------------------------------------------------------------------------------------------
def fp(x):
    return rr.fmt_pct(x)


def mean_(xs):
    return rr.mean(xs)


def pct_cell(a, key):
    v = a.get(key)
    if not v or mean_(v) is None:
        return "n/a"
    r = rr.rng(v)
    return fp(mean_(v)) + (f" ({r[0]:.1f}-{r[1]:.1f})" if r and r[0] != r[1] else "")


def comparison_table(M, err_counts, G, present) -> str:
    cols = present
    A = M["arms"]

    def cell(arm, f):
        a = A.get(arm)
        if not a:
            return "n/a"
        try:
            v = f(a)
            return "n/a" if v is None else v
        except (KeyError, TypeError, ValueError):
            return "n/a"

    L = [f"# {fa.EXPERIMENT}: comparison table (all arms, every metric)", "",
         "All 42 questions, 3 runs per arm; percentages are the mean over runs (min-max range in brackets when the runs differ). Reused arms (B2, C_*) come from "
         "results/kg_hardening_eval/ and were produced on identical retrieval/generation code (see run_manifest.json -> reused_arms_verification). 'n/a' = the metric cannot "
         "exist for that arm (A has no retrieval).", "",
         "## Correctness", "", "| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    L.append("| correctness, partial credit (all 42) | " + " | ".join(cell(a, lambda x: pct_cell(x, "correctness.all")) for a in cols) + " |")
    L.append("| correctness, strict (fully correct in a majority of runs) | " + " | ".join(cell(a, lambda x: fp(x["correctness_strict_pct"])) for a in cols) + " |")
    L.append("| correctness, lenient (score >= 1 in a majority of runs) | " + " | ".join(cell(a, lambda x: fp(x["correctness_lenient_pct"])) for a in cols) + " |")
    L.append("| correctness, original 22 (E14a core), partial credit | " + " | ".join(cell(a, lambda x: pct_cell(x, "correctness.core")) for a in cols) + " |")
    for c in rr.CATS:
        n = sum(1 for q in M["questions"].values() if q["category"] == c)
        L.append(f"| correctness, {c} ({n}) | " + " | ".join(cell(a, lambda x, c=c: pct_cell(x, f"correctness.{c}")) for a in cols) + " |")
    L += ["", "## Judge metrics", "", "| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for name, key in (("relevance", "relevance"), ("groundedness", "groundedness"), ("hallucination vs reference evidence", "halluc_ref"), ("hallucination vs retrieved context", "halluc_ctx")):
        L.append(f"| {name} | " + " | ".join(cell(a, lambda x, key=key: pct_cell(x, key)) for a in cols) + " |")
    for name, key in (("citation coverage", "cov"), ("citation correctness", "correct"), ("unsupported-claim rate", "unsup")):
        L.append(f"| {name} | " + " | ".join(cell(a, lambda x, key=key: fp(mean_(x["citation"]["per_run"][key])) if x.get("citation") else None) for a in cols) + " |")
    L += ["", "## Retrieval (25 document questions, run 1) and database-row coverage", "", "| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for key in ("R@1", "R@3", "R@5", "R@10", "MRR@10"):
        L.append(f"| {key} | " + " | ".join(cell(a, lambda x, key=key: rr.fmt_ratio(x["retrieval_docq"][key]) if x.get("retrieval_docq") else None) for a in cols) + " |")
    L.append("| retrieval identical across runs | " + " | ".join(cell(a, lambda x: None if x["retrieval_deterministic_across_runs"] is None else str(x["retrieval_deterministic_across_runs"])) for a in cols) + " |")
    L.append("| database-row coverage | " + " | ".join(cell(a, lambda x: pct_cell(x, "db_rowcov") if x.get("db_rowcov") else None) for a in cols) + " |")
    L += ["", "## Latency, prompt size, abstentions, routing, variability", "", "| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    L.append("| latency median | " + " | ".join(cell(a, lambda x: rr.fmt_s(x["latency_median_s"])) for a in cols) + " |")
    L.append("| latency p95 | " + " | ".join(cell(a, lambda x: rr.fmt_s(x["latency_p95_s"])) for a in cols) + " |")
    L.append("| latency records excluded (gap/slow) | " + " | ".join(cell(a, lambda x: str(x["latency_records_excluded"])) for a in cols) + " |")
    L.append("| prompt tokens median | " + " | ".join(cell(a, lambda x: rr.fmt_int(x["prompt_tokens_median"])) for a in cols) + " |")
    L.append("| abstentions (records) | " + " | ".join(cell(a, lambda x: str(x["n_abstained"])) for a in cols) + " |")
    L.append("| routes (final) | " + " | ".join(cell(a, lambda x: json.dumps(x["routes"]) if x["routes"] else "no router") for a in cols) + " |")
    L.append("| router errors | " + " | ".join(cell(a, lambda x: str(x["router_errors"])) for a in cols) + " |")
    L.append("| questions with identical correctness in all runs | " + " | ".join(cell(a, lambda x: f"{x['variability']['identical_correctness']}/{x['variability']['questions_compared_correctness']}") for a in cols) + " |")
    L.append("| questions with identical answer text in all runs | " + " | ".join(cell(a, lambda x: f"{x['variability']['identical_answer_text']}/{x['variability']['questions_compared_text']}") for a in cols) + " |")
    L.append("| correctness per run (partial) | " + " | ".join(cell(a, lambda x: json.dumps(x["correctness.all"])) for a in cols) + " |")
    ecols = [a for a in cols if a in err_counts]
    L += ["", "## Error causes (answers with correctness < 2; v3 rule; reference B2 of the same run for router / layer arms; A not classified)", "",
          "| cause | " + " | ".join(ecols) + " |", "|---|" + "---|" * len(ecols)]
    for c in rr.CAUSES:
        L.append(f"| {c} | " + " | ".join(str(err_counts[a][c]) for a in ecols) + " |")
    L.append("| total | " + " | ".join(str(sum(err_counts[a].values())) for a in ecols) + " |")
    if G["arms"]:
        garms = list(G["arms"])
        gs = {a: G["arms"][a]["summary"] for a in garms}
        L += ["", "## What the graph added (run 1; reference B2; see graph_diagnostics.md)", "", "| item | " + " | ".join(garms) + " |", "|---|" + "---|" * len(garms)]
        for name, f in (("questions with chunks added", lambda s: str(s["questions_with_added_chunks"])), ("chunks added (total)", lambda s: str(s["added_chunks_total"])),
                        ("documents added (total)", lambda s: str(s["added_documents_total"])), ("added chunks that reached the prompt", lambda s: str(s["added_in_prompt"])),
                        ("added via RELATED_TO link", lambda s: str(s["added_via"].get("RELATED_TO", 0))), ("added via bridge concept, hub-only", lambda s: str(s["added_via"].get("bridge concept (hub-only)", 0))),
                        ("added via bridge concept, has a specific concept", lambda s: str(s["added_via"].get("bridge concept (has a specific concept)", 0))),
                        ("added chunks that are gold", lambda s: f"{s['added_relevant']} of {s['added_chunks_total']}"),
                        ("gold at rank 1 (B2 / this arm), 25 doc questions", lambda s: f"{s['gold_rank_1_B2']} / {s['gold_rank_1_arm']}"),
                        ("gold rank vs B2 (better / same / worse / lost)", lambda s: f"{s['gold_rank_changes']['better']} / {s['gold_rank_changes']['same']} / {s['gold_rank_changes']['worse']} / {s['gold_rank_changes']['lost_from_top10']}"),
                        ("gold rank worse or lost on", lambda s: str(s["gold_rank_worse_or_lost_questions"] or "none")),
                        ("questions where graph chunks displaced the gold from the top 10", lambda s: f"{len(s['displaced_questions'])} {s['displaced_questions']}"),
                        ("RELATED_TO documents appended by the layer (run 1)", lambda s: str(s["link_docs_added_total"]))):
            L.append(f"| {name} | " + " | ".join(f(gs[a]) for a in garms) + " |")
    return "\n".join(L)


def paired_markdown(M) -> str:
    L = [f"# {fa.EXPERIMENT}: paired comparisons", "",
         "Question level, 42 pairs; wins = first arm better on that question; exact two-sided McNemar on the discordant pairs; paired bootstrap 95% CI "
         "(10,000 question resamples, seed 20261031) in points of the per-question value. strict: fully correct in a majority of runs; partial: per-question mean "
         "score / 2; lenient: score >= 1 in a majority of runs. Fewer than 10 discordant pairs = low power: the p value cannot reach 0.05 for small w/l splits.", ""]
    for rule in RULES:
        L += [f"## Rule: {rule}", "", "| comparison | wins | losses | ties | McNemar p | 95% CI (pts) | mean diff (pts) | discordant < 10 | wins on | losses on |", "|---|---|---|---|---|---|---|---|---|---|"]
        for a, b in fa.COMPARISONS:
            p = M["paired"].get(f"{a}_vs_{b}", {}).get(rule)
            if not p or p["ci95_pts"] is None:
                L.append(f"| {a} vs {b} | n/a | n/a | n/a | n/a | n/a | n/a | | an arm is missing or unscored | |")
                continue
            L.append(f"| {a} vs {b} | {p['wins']} | {p['losses']} | {p['ties']} | {p['p_mcnemar_exact']:.4f} | [{p['ci95_pts'][0]:+.1f}, {p['ci95_pts'][1]:+.1f}] | {p['mean_diff_pts']:+.1f} | "
                     f"{'yes' if p['fewer_than_10_discordant'] else ''} | {p['win_ids']} | {p['loss_ids']} |")
        L.append("")
    return "\n".join(L)


def ablation_markdown(M, G) -> str:
    A = M["arms"]
    L = ["# Component ablation (each row adds ONE component to B2 unless stated) and graph-vs-router separation", "",
         "Means over 3 runs. Old merge = integration/rag/pipeline.py::_semantic_merge before the 2026-11-11 fix (weighted-RRF bonus): every graph arm in this table was measured with it.", "",
         "| component | arm | description | correctness partial | strict | lenient | original 22 | groundedness | R@1 | MRR@10 | db-row coverage |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, arm, desc in ABLATION_ROWS:
        if arm is None or arm not in A:
            L.append(f"| {name} | - | {desc} | not run (not wired into retrieval) | | | | | | | |" if arm is None else f"| {name} | {arm} | {desc} | not run | | | | | | | |")
            continue
        a = A[arm]
        ret = a.get("retrieval_docq") or {}
        L.append(f"| {name} | {arm} | {desc} | {fp(mean_(a['correctness.all']))} | {fp(a['correctness_strict_pct'])} | {fp(a['correctness_lenient_pct'])} | {fp(mean_(a['correctness.core']))} | "
                 f"{fp(mean_(a['groundedness']))} | {rr.fmt_ratio(ret.get('R@1'))} | {rr.fmt_ratio(ret.get('MRR@10'))} | {fp(mean_(a['db_rowcov']))} |")
    L += ["", "## 2x2: graph effect vs router effect (correctness, partial credit, mean of 3 runs; differences in points)", ""]
    for graph_arm, c_arm, label in (("G1", "C_V1", "hardened graph"), ("G0", "C_V0", "legacy graph")):
        if not all(x in A for x in ("B2", "R", graph_arm, c_arm)):
            L.append(f"({label}: an arm is missing)")
            continue
        v = {x: mean_(A[x]["correctness.all"]) for x in ("B2", "R", graph_arm, c_arm)}
        L += [f"### {label} ({graph_arm} / {c_arm})", "", "| | router OFF | router ON | router effect |", "|---|---|---|---|",
              f"| graph OFF | B2 {fp(v['B2'])} | R {fp(v['R'])} | {v['R'] - v['B2']:+.1f} pts |",
              f"| graph ON | {graph_arm} {fp(v[graph_arm])} | {c_arm} {fp(v[c_arm])} | {v[c_arm] - v[graph_arm]:+.1f} pts |",
              f"| graph effect | {v[graph_arm] - v['B2']:+.1f} pts | {v[c_arm] - v['R']:+.1f} pts | interaction {(v[c_arm] - v['R']) - (v[graph_arm] - v['B2']):+.1f} pts |", ""]
        for key in (f"{graph_arm}_vs_B2", f"{c_arm}_vs_R", "R_vs_B2", f"{c_arm}_vs_{graph_arm}"):
            p = M["paired"].get(key, {}).get("partial")
            if p:
                L.append(f"* {key.replace('_vs_', ' vs ')} (partial): {p['wins']}/{p['losses']}/{p['ties']}, p={p['p_mcnemar_exact']:.3f}, CI [{p['ci95_pts'][0]:+.1f}, {p['ci95_pts'][1]:+.1f}]")
        L.append("")
    return "\n".join(L)


def per_question_csv(qs, raw, scored, present, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        head = ["id", "category", "is_core"]
        for a in present:
            head += [f"{a}_run1", f"{a}_run2", f"{a}_run3", f"{a}_mean_pct"]
        garms = [a for a in present if a in fa.GRAPH_ARMS or a in ("C_V0", "C_V1", "C_V1_links", "R")]
        for a in garms:
            head += [f"{a}_route", f"{a}_graph_weight", f"{a}_added_chunks_run1"]
        w.writerow(head)
        for qid, q in qs.items():
            row = [qid, q["category"], q["is_core"]]
            for a in present:
                v = [scored.get((a, qid, r), {}).get("correctness") for r in RUNS]
                vv = [x for x in v if x is not None]
                row += [("" if x is None else x) for x in v] + [round(100 * sum(vv) / (2 * len(vv)), 1) if vv else ""]
            for a in garms:
                rec = raw.get((a, qid, 1)) or {}
                row += [(rec.get("route") or {}).get("final", ""), (rec.get("semantic") or {}).get("graph_weight", ""), len((rec.get("semantic") or {}).get("added_chunks") or [])]
            w.writerow(row)


def flat_values(M, err_counts, G) -> dict:
    V = {"experiment": fa.EXPERIMENT, "manifest_git_commit": M.get("manifest_git_commit"), "n_questions": 42, "runs_per_arm": 3}
    for arm, a in M["arms"].items():
        def put(k, v):
            V[f"{arm}.{k}"] = "n/a" if v is None else v
        put("correctness_partial", mean_(a["correctness.all"])); put("correctness_strict", a["correctness_strict_pct"]); put("correctness_lenient", a["correctness_lenient_pct"])
        put("correctness_core22", mean_(a["correctness.core"]))
        for c in rr.CATS:
            put(f"correctness_{c}", mean_(a[f"correctness.{c}"]))
        for k in ("relevance", "groundedness", "halluc_ref", "halluc_ctx"):
            put(k, mean_(a[k]))
        cit = a.get("citation")
        put("cite_cov", mean_(cit["per_run"]["cov"]) if cit else None); put("cite_correct", mean_(cit["per_run"]["correct"]) if cit else None); put("unsupported", mean_(cit["per_run"]["unsup"]) if cit else None)
        ret = a.get("retrieval_docq") or {}
        for k, name in (("R@1", "r1"), ("R@3", "r3"), ("R@5", "r5"), ("R@10", "r10"), ("MRR@10", "mrr10")):
            put(name, ret.get(k))
        put("db_rowcov", mean_(a["db_rowcov"]) if a.get("db_rowcov") else None)
        put("latency_median_s", a["latency_median_s"]); put("latency_p95_s", a["latency_p95_s"]); put("prompt_tokens_median", a["prompt_tokens_median"])
        put("n_abstained", a["n_abstained"]); put("n_records", a["n_records"]); put("n_scored", a["n_scored"])
        put("identical_correctness_questions", a["variability"]["identical_correctness"]); put("identical_answer_text_questions", a["variability"]["identical_answer_text"])
        put("correctness_partial_per_run", a["correctness.all"])
        if arm in err_counts:
            for c in rr.CAUSES:
                V[f"err.{arm}.{c}"] = err_counts[arm][c]
            V[f"err.{arm}.total"] = sum(err_counts[arm].values())
    for key, rules in M["paired"].items():
        for rule, p in rules.items():
            base = f"paired.{key}.{rule}"
            V[f"{base}.wins"], V[f"{base}.losses"], V[f"{base}.ties"] = p["wins"], p["losses"], p["ties"]
            V[f"{base}.p_mcnemar"] = p["p_mcnemar_exact"]
            V[f"{base}.ci_lo"], V[f"{base}.ci_hi"] = (p["ci95_pts"] or [None, None])
            V[f"{base}.mean_diff_pts"] = p["mean_diff_pts"]
            V[f"{base}.discordant_lt_10"] = p["fewer_than_10_discordant"]
    for arm, g in G["arms"].items():
        s = g["summary"]
        for k in ("questions_with_added_chunks", "added_chunks_total", "added_documents_total", "added_in_prompt", "added_relevant", "gold_rank_1_B2", "gold_rank_1_arm", "link_docs_added_total"):
            V[f"graph.{arm}.{k}"] = s[k]
        for k, v in s["gold_rank_changes"].items():
            V[f"graph.{arm}.gold_rank_{k}"] = v
        for k, v in s["added_via"].items():
            V[f"graph.{arm}.added_via.{k}"] = v
        V[f"graph.{arm}.displaced_questions"] = s["displaced_questions"]
        V[f"graph.{arm}.gold_rank_worse_or_lost_questions"] = s["gold_rank_worse_or_lost_questions"]
    V["structured_kg"] = "not run (not wired into retrieval)"
    return V


# ---------------------------------------------------------------------------------------------------------------------------------
def main() -> None:
    qs, raw, scored = load()
    present = [a for a in ARMS if any(key[0] == a for key in raw)]
    missing = [key for key in raw if key[0] in fa.ARMS_NEW and key not in scored]
    if missing:
        print(f"WARNING: {len(missing)} raw records of the generated arms are not scored yet (report is partial)")
    flagged = h.flag_latency_records([raw[key] for key in sorted(raw, key=lambda key: raw[key].get("timestamp_utc") or "") if key[0] in fa.ARMS_NEW])
    manifest = json.loads((RES / "run_manifest.json").read_text(encoding="utf-8")) if (RES / "run_manifest.json").exists() else None
    M = {"definitions": __doc__, "experiment": fa.EXPERIMENT, "manifest_git_commit": (manifest or {}).get("git", {}).get("commit"),
         "questions": {q: {"category": qs[q]["category"], "is_core": qs[q]["is_core"]} for q in qs}, "arms_present": present,
         "runs_per_arm": {a: len(runs_of(raw, a)) for a in present}, "arms": {}}
    for arm in present:
        M["arms"][arm] = arm_block(arm, qs, raw, scored, runs_of(raw, arm), flagged if arm in fa.ARMS_NEW else {})
    M["paired"] = {}
    for a, b in fa.COMPARISONS:
        if a in present and b in present:
            M["paired"][f"{a}_vs_{b}"] = {rule: paired_rule(a, b, qs, scored, RUNS, rule) for rule in RULES}
    err_rows, err_counts = error_analysis(qs, raw, scored)
    M["error_analysis"] = {"counts": err_counts, "totals": {a: sum(c.values()) for a, c in err_counts.items()}, "not_classified": ["A (no retrieval)"]}
    with open(RES / "error_table.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["arm", "run", "id", "category", "correctness", "cause", "detail"])
        w.writeheader(); w.writerows(err_rows)
    G = graph_diagnostics(qs, raw)
    M["graph_diagnostics_summary"] = {a: G["arms"][a]["summary"] for a in G["arms"]}
    (RES / "graph_diagnostics.json").write_text(json.dumps(G, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (RES / "graph_diagnostics.md").write_text(graph_markdown(G), encoding="utf-8")
    (RES / "metrics.json").write_text(json.dumps(M, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (RES / "comparison_table.md").write_text(comparison_table(M, err_counts, G, present), encoding="utf-8")
    (RES / "paired_comparisons.md").write_text(paired_markdown(M), encoding="utf-8")
    if fa.EXPERIMENT == "final_ablation":
        (RES / "ablation_table.md").write_text(ablation_markdown(M, G), encoding="utf-8")
    per_question_csv(qs, raw, scored, present, RES / "per_question_scores.csv")
    (RES / "values.json").write_text(json.dumps(flat_values(M, err_counts, G), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(comparison_table(M, err_counts, G, present))
    print()
    print(paired_markdown(M))
    print("written:", ", ".join(["metrics.json", "values.json", "comparison_table.md", "paired_comparisons.md", "graph_diagnostics.md/.json", "error_table.csv", "per_question_scores.csv"]
                                + (["ablation_table.md"] if fa.EXPERIMENT == "final_ablation" else [])))


if __name__ == "__main__":
    main()
