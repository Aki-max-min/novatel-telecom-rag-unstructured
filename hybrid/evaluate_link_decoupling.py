"""
E13 link decoupling - evaluation exactly as pre-declared in docs/E13_link_decoupling_rule.md.

Cells: links ON with w_link in {0.15, 0.30, 0.50} vs the baseline (graph off, links off). Dev sets: main 29, mini 9,
validation 14 (not Person A's 42). Win/loss on document-level Recall@3 as in docs/E13_kg_hardening_rule.md.
Adoption: pooled losses <= 1 AND no dev set net < -1 AND, on the 5-question incident mechanism check, links-on gets at least
one more pair into the final top 5 than links-off. 5 pairs is a mechanism check, not generalisation evidence.

Run once in the rag-api environment:  python hybrid/evaluate_link_decoupling.py
Writes docs/E13_link_decoupling_results.md and knowledge_graph/output_hardening/link_decoupling_results.json (gitignored).
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

from knowledge_graph.evaluate_hardening import CachedRetriever, CachedScorer, SETS, load_sets, metrics  # noqa: E402
from fusion import fuse_and_select  # noqa: E402
from pipeline import run_hybrid_retrieval  # noqa: E402
from query_gate import classify_query, graph_weight  # noqa: E402
from rerank import _load_model, controlled_rerank  # noqa: E402
from retrievers import build_candidates, link_candidates_for, load_context  # noqa: E402

W_LINKS = (0.15, 0.30, 0.50)
INCIDENT = REPO_ROOT / "hybrid" / "benchmark" / "incident_link_check.json"
OUT_MD = REPO_ROOT / "docs" / "E13_link_decoupling_results.md"
OUT_JSON = REPO_ROOT / "knowledge_graph" / "output_hardening" / "link_decoupling_results.json"


def final_top5(question, ctx, scorer, w_link):
    """Final top-5 document ids; w_link None = baseline (graph off, links off)."""
    vector, graph, _ = build_candidates(question, ctx["retriever"], ctx["graph_index"], ctx["corpus"], ctx["person_a"],
                                        graph_enabled=False)
    links = []
    if w_link is not None:
        links = link_candidates_for(vector, ctx["graph_index"], ctx["corpus"], ctx["person_a"].load_chunk_text)
    final = run_hybrid_retrieval(question, vector, graph, top_k=5, model=scorer, link_candidates=links,
                                 link_weight=(w_link or 0.0))
    return [c["metadata"]["document_id"] for c in final], [c["metadata"]["document_id"] for c in links]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sets = load_sets()
    ctx = load_context()
    ctx = dict(ctx, retriever=CachedRetriever(ctx["retriever"]))
    scorer = CachedScorer(_load_model())
    expected = {s: [e for _, e in sets[s]] for s in SETS}
    questions = {s: [q for q, _ in sets[s]] for s in SETS}

    def run(w_link):
        out, added = {}, {}
        for s in SETS:
            rows = [final_top5(q, ctx, scorer, w_link) for q in questions[s]]
            out[s], added[s] = [r[0] for r in rows], [r[1] for r in rows]
        return out, added

    base_rank, _ = run(None)
    base = {s: metrics(base_rank[s], expected[s]) for s in SETS}
    base["pooled"] = metrics([r for s in SETS for r in base_rank[s]], [e for s in SETS for e in expected[s]])

    cells = {}
    for w in W_LINKS:
        rankings, added = run(w)
        row = {"w_link": w, "per_set": {}, "per_question": {}}
        wins = losses = 0
        for s in SETS:
            w_, l_, per_q = 0, 0, []
            for q, b, c, e, a in zip(questions[s], base_rank[s], rankings[s], expected[s], added[s]):
                bh, ch = bool(set(b[:3]) & e), bool(set(c[:3]) & e)
                if (not bh) and ch:
                    w_ += 1
                    per_q.append({"question": q, "outcome": "win", "expected": sorted(e), "baseline_top3": b[:3],
                                  "config_top3": c[:3], "links_added": a})
                elif bh and not ch:
                    l_ += 1
                    per_q.append({"question": q, "outcome": "loss", "expected": sorted(e), "baseline_top3": b[:3],
                                  "config_top3": c[:3], "links_added": a})
            row["per_set"][s] = {"wins": w_, "losses": l_, "net": w_ - l_, "questions_with_links_added":
                                 sum(bool(x) for x in added[s]), **metrics(rankings[s], expected[s])}
            row["per_question"][s] = per_q
            wins, losses = wins + w_, losses + l_
        pooled_rank = [r for s in SETS for r in rankings[s]]
        row["pooled"] = {"wins": wins, "losses": losses, "net": wins - losses,
                         **metrics(pooled_rank, [e for s in SETS for e in expected[s]])}
        cells[w] = row
        print(f"w_link={w}: pooled wins={wins} losses={losses} net={wins - losses:+d} "
              + " ".join(f"{s}:{row['per_set'][s]['net']:+d}" for s in SETS), flush=True)

    # incident mechanism check
    items = json.loads(INCIDENT.read_text(encoding="utf-8"))["questions"]
    incident = {"off": [], "on": {w: [] for w in W_LINKS}}
    for item in items:
        pair = set(item["pair"])
        off, _ = final_top5(item["question"], ctx, scorer, None)
        incident["off"].append(pair <= set(off))
        for w in W_LINKS:
            on, _ = final_top5(item["question"], ctx, scorer, w)
            incident["on"][w].append(pair <= set(on))
    off_pairs = sum(incident["off"])
    on_pairs = {w: sum(v) for w, v in incident["on"].items()}

    # selection (highest pooled net; ties -> smaller w_link) and the pre-declared adoption rule
    selected_w = sorted(W_LINKS, key=lambda w: (-cells[w]["pooled"]["net"], w))[0]
    sel = cells[selected_w]
    cond_losses = sel["pooled"]["losses"] <= 1
    cond_sets = min(sel["per_set"][s]["net"] for s in SETS) >= -1
    cond_incident = on_pairs[selected_w] >= off_pairs + 1
    verdict = cond_losses and cond_sets and cond_incident

    trace = trace_il4(items, ctx, scorer, selected_w)
    payload = {"baseline": base, "cells": {str(w): c for w, c in cells.items()}, "selected_w_link": selected_w,
               "incident": {"links_off_pairs": off_pairs, "links_on_pairs": {str(w): n for w, n in on_pairs.items()},
                            "per_question_off": incident["off"], "per_question_on": {str(w): v for w, v in incident["on"].items()}},
               "adoption": {"pooled_losses_le_1": cond_losses, "no_set_net_below_-1": cond_sets,
                            "incident_gain_ge_1": cond_incident, "verdict": "PASS" if verdict else "FAIL"}}
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    write_md(payload, cells, base, selected_w, items, incident, trace)
    print(f"incident pairs in final top 5: links off {off_pairs}/5, links on {on_pairs}")
    print(f"SELECTED w_link={selected_w}: pooled net {sel['pooled']['net']:+d} (losses {sel['pooled']['losses']}), "
          f"conditions: losses<=1 {cond_losses}, no set < -1 {cond_sets}, incident gain>=1 {cond_incident} -> "
          f"ADOPTION {'PASS' if verdict else 'FAIL'}")
    print(f"written: {OUT_MD}")


def trace_il4(items, ctx, scorer, w_link):
    item = next(i for i in items if i["question_id"] == "IL4")
    q, pair = item["question"], item["pair"]
    vector, graph, _ = build_candidates(q, ctx["retriever"], ctx["graph_index"], ctx["corpus"], ctx["person_a"],
                                        graph_enabled=False)
    links = link_candidates_for(vector, ctx["graph_index"], ctx["corpus"], ctx["person_a"].load_chunk_text)
    fused = fuse_and_select(vector, graph, q, top_k=20, link_candidates=links, link_weight=w_link)
    ranked = controlled_rerank(q, fused, max_pool=20, top_k=20, model=scorer)
    d = lambda cs: [c["metadata"]["document_id"] for c in cs]  # noqa: E731
    return {"question": q, "gate_graph_weight": graph_weight(classify_query(q)), "w_link": w_link, "pair": pair,
            "vector_top10": d(vector), "link_list": d(links), "fusion_order": d(fused),
            "fusion_sources": {c["metadata"]["document_id"]: c["fusion_sources"] for c in fused if c["metadata"]["document_id"] in pair},
            "final_order": d(ranked), "final_top5": d(ranked)[:5],
            "partner_ranks": {doc: ({"rank_fusion": next(c["rank_fusion"] for c in ranked if c["metadata"]["document_id"] == doc),
                                     "rank_rerank": next(c["rank_rerank"] for c in ranked if c["metadata"]["document_id"] == doc),
                                     "final_rank": d(ranked).index(doc) + 1} if doc in d(ranked) else None) for doc in pair}}


def fmt(x):
    return f"{x:.4f}"


def write_md(payload, cells, base, selected_w, items, incident, trace):
    a = payload["adoption"]
    L = ["# E13 link decoupling - results", "",
         "Run exactly as pre-declared in `docs/E13_link_decoupling_rule.md`. Change under test: resolved RELATED_TO neighbours of the top-3 vector "
         "documents (cap 2) form their own fusion list with weight `w_link`, independent of the gate graph weight; the concept list is off, as in "
         "the current default. Baseline = graph off, links off. Dev sets only (main 29, mini 9, validation 14); Person A's 42 questions were not used. "
         "Reproduce: `python hybrid/evaluate_link_decoupling.py` (rag-api environment).", "",
         "## Baseline", "", "| set | R@1 | R@3 | R@5 | MRR@5 |", "|---|---|---|---|---|"]
    for s in list(SETS) + ["pooled"]:
        b = base[s]
        L.append(f"| {s} | {fmt(b['R@1'])} | {fmt(b['R@3'])} | {fmt(b['R@5'])} | {fmt(b['MRR@5'])} |")
    L += ["", "## Cells", "",
          "| w_link | pooled W/L/net | main29 W/L | mini9 W/L | val14 W/L | questions where links were added (main/mini/val) | pooled R@1 | R@3 | MRR@5 (secondary) | incident pairs in final top 5 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for w, c in cells.items():
        ps, p = c["per_set"], c["pooled"]
        L.append(f"| {w} | {p['wins']}/{p['losses']}/{p['net']:+d} | {ps['main29']['wins']}/{ps['main29']['losses']} | "
                 f"{ps['mini9']['wins']}/{ps['mini9']['losses']} | {ps['validation14']['wins']}/{ps['validation14']['losses']} | "
                 f"{ps['main29']['questions_with_links_added']}/{ps['mini9']['questions_with_links_added']}/{ps['validation14']['questions_with_links_added']} | "
                 f"{fmt(p['R@1'])} | {fmt(p['R@3'])} | {fmt(p['MRR@5'])} | {payload['incident']['links_on_pairs'][str(w)]}/5 (off: {payload['incident']['links_off_pairs']}/5) |")
    L += ["", "## Selection and verdict by the pre-declared rule", "",
          f"Selected (highest pooled net; ties: smaller w_link): **w_link = {selected_w}**.", "",
          f"- pooled losses <= 1: **{a['pooled_losses_le_1']}**", f"- no dev set net < -1: **{a['no_set_net_below_-1']}**",
          f"- incident check, links-on gets at least one more pair into the final top 5 than links-off: **{a['incident_gain_ge_1']}** "
          f"(on {payload['incident']['links_on_pairs'][str(selected_w)]}/5 vs off {payload['incident']['links_off_pairs']}/5)", "",
          f"**Verdict: {a['verdict']}.**" + ("" if a["verdict"] == "PASS" else " Links stay OFF by default (`LINKS_ENABLED = False`); negative result."),
          "", "Five incident pairs is a mechanism check, not generalisation evidence.", "",
          "## Per-question wins and losses of the selected cell", ""]
    any_row = False
    for s in SETS:
        for item in cells[selected_w]["per_question"][s]:
            any_row = True
            L.append(f"- [{s}] **{item['outcome'].upper()}** {item['question']} expected={item['expected']} baseline top3={item['baseline_top3']} "
                     f"config top3={item['config_top3']} links added={item['links_added']}")
    if not any_row:
        L.append("(none: the selected cell changed no question's top-3 outcome)")
    L += ["", "## Incident mechanism check, per question", "", "| question | links off | " + " | ".join(f"on w={w}" for w in W_LINKS) + " |",
          "|---|---|" + "---|" * len(W_LINKS)]
    for i, item in enumerate(items):
        L.append(f"| {item['question_id']} | {'pair in top 5' if incident['off'][i] else 'pair NOT in top 5'} | "
                 + " | ".join('pair in top 5' if incident['on'][w][i] else 'pair NOT in top 5' for w in W_LINKS) + " |")
    t = trace
    L += ["", f"## Trace of IL4 with links on (w_link = {t['w_link']})", "", f"Question: {t['question']}", "",
          f"- gate graph weight: {t['gate_graph_weight']} (the concept list stays off; the link list does not depend on it)",
          f"- vector top-10: {t['vector_top10']}", f"- link list: {t['link_list']}", f"- fusion order: {t['fusion_order']}",
          f"- fusion sources of the pair: {t['fusion_sources']}", f"- final top 5: {t['final_top5']}",
          f"- pair documents (fusion rank / rerank-only rank / final rank): {t['partner_ranks']}", "",
          "IL1 is a reranker miss (the CrossEncoder ranked the partner 9 of 9 in the pool); the reranker is not changed here."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
