"""
E13 graph-fusion fix - the single measurement declared in docs/E13_graph_fusion_fix.md (rule committed before
this run). Arms: graph OFF (today's default) vs graph ON (concept candidates with default graph_expand arguments
+ resolved-RELATED_TO links), same rerank mode as today, append-only fusion.

Dev sets only (main 29, mini 9, validation 14; not Person A's 42). Reports R@1/R@3/R@5/MRR@5 per set and pooled,
per-question wins/losses at R@1 and at R@3, and the 5 incident pairs on vs off. Adoption rule: GRAPH_ENABLED and
LINKS_ENABLED go True only if no dev question is lost at R@1 or at R@3 versus off.

Run once in the rag-api environment:  python hybrid/evaluate_fusion_fix.py
Writes knowledge_graph/output_hardening/fusion_fix_results.json (gitignored); the table goes into
docs/E13_graph_fusion_fix.md by hand.
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
from pipeline import run_hybrid_retrieval  # noqa: E402
from query_gate import classify_query, graph_weight  # noqa: E402
from rerank import _load_model  # noqa: E402
from retrievers import build_candidates, link_candidates_for, load_context  # noqa: E402

INCIDENT = REPO_ROOT / "hybrid" / "benchmark" / "incident_link_check.json"
OUT_JSON = REPO_ROOT / "knowledge_graph" / "output_hardening" / "fusion_fix_results.json"


def final_top5(question, ctx, scorer, graph_on):
    vector, graph, _ = build_candidates(question, ctx["retriever"], ctx["graph_index"], ctx["corpus"],
                                        ctx["person_a"], graph_enabled=graph_on)
    links = []
    if graph_on:
        links = link_candidates_for(vector, ctx["graph_index"], ctx["corpus"], ctx["person_a"].load_chunk_text)
    final = run_hybrid_retrieval(question, vector, graph, top_k=5, model=scorer, link_candidates=links)
    return ([c["metadata"]["document_id"] for c in final],
            {"vector_top10": [c["metadata"]["document_id"] for c in vector],
             "graph_list": [c["metadata"]["document_id"] for c in graph],
             "link_list": [c["metadata"]["document_id"] for c in links],
             "gate_weight": graph_weight(classify_query(question))})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sets = load_sets()
    ctx = load_context()
    ctx = dict(ctx, retriever=CachedRetriever(ctx["retriever"]))
    scorer = CachedScorer(_load_model())
    expected = {s: [e for _, e in sets[s]] for s in SETS}
    questions = {s: [q for q, _ in sets[s]] for s in SETS}

    rankings, traces = {}, {}
    for arm, graph_on in (("off", False), ("on", True)):
        rankings[arm], traces[arm] = {}, {}
        for s in SETS:
            rows = [final_top5(q, ctx, scorer, graph_on) for q in questions[s]]
            rankings[arm][s] = [r[0] for r in rows]
            traces[arm][s] = [r[1] for r in rows]

    results = {"per_set": {}, "pooled": {}, "wins_losses": {}, "losing_questions": []}
    for arm in ("off", "on"):
        results["per_set"][arm] = {s: metrics(rankings[arm][s], expected[s]) for s in SETS}
        results["pooled"][arm] = metrics([r for s in SETS for r in rankings[arm][s]],
                                         [e for s in SETS for e in expected[s]])

    total = {f"{m}_{w}": 0 for m in ("R@1", "R@3") for w in ("wins", "losses")}
    for s in SETS:
        wl = {"R@1_wins": 0, "R@1_losses": 0, "R@3_wins": 0, "R@3_losses": 0, "detail": []}
        for q, off, on, e in zip(questions[s], rankings["off"][s], rankings["on"][s], expected[s]):
            for k, name in ((1, "R@1"), (3, "R@3")):
                off_hit, on_hit = bool(set(off[:k]) & e), bool(set(on[:k]) & e)
                if on_hit and not off_hit:
                    wl[f"{name}_wins"] += 1
                    wl["detail"].append({"metric": name, "outcome": "win", "question": q, "expected": sorted(e),
                                         "off_top5": off, "on_top5": on})
                elif off_hit and not on_hit:
                    wl[f"{name}_losses"] += 1
                    idx = questions[s].index(q)
                    wl["detail"].append({"metric": name, "outcome": "loss", "question": q, "expected": sorted(e),
                                         "off_top5": off, "on_top5": on, "trace_on": traces["on"][s][idx]})
                    results["losing_questions"].append({"set": s, "metric": name, "question": q,
                                                        "expected": sorted(e), "off_top5": off, "on_top5": on,
                                                        "trace_on": traces["on"][s][idx]})
        results["wins_losses"][s] = wl
        for key in total:
            total[key] += wl[key]
        print(f"{s:<13} R@1 W/L {wl['R@1_wins']}/{wl['R@1_losses']}   R@3 W/L {wl['R@3_wins']}/{wl['R@3_losses']}")
    results["wins_losses"]["pooled"] = total

    items = json.loads(INCIDENT.read_text(encoding="utf-8"))["questions"]
    incident = {}
    for arm, graph_on in (("off", False), ("on", True)):
        incident[arm] = []
        for item in items:
            top5, _ = final_top5(item["question"], ctx, scorer, graph_on)
            incident[arm].append({"question_id": item["question_id"], "pair_in_top5": set(item["pair"]) <= set(top5),
                                  "top5": top5})
    results["incident"] = incident

    verdict = (total["R@1_losses"] == 0 and total["R@3_losses"] == 0)
    results["adoption"] = {"rule": "no dev question lost at R@1 or R@3 vs graph off",
                           "pooled_losses_R@1": total["R@1_losses"], "pooled_losses_R@3": total["R@3_losses"],
                           "verdict": "ADOPT (GRAPH_ENABLED=True, LINKS_ENABLED=True)" if verdict
                           else "DO NOT ADOPT (both stay False)"}

    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=1, ensure_ascii=False, default=list), encoding="utf-8")

    for s in list(SETS):
        off, on = results["per_set"]["off"][s], results["per_set"]["on"][s]
        print(f"{s:<13} off R@1 {off['R@1']:.4f} R@3 {off['R@3']:.4f} R@5 {off['R@5']:.4f} MRR {off['MRR@5']:.4f} | "
              f"on R@1 {on['R@1']:.4f} R@3 {on['R@3']:.4f} R@5 {on['R@5']:.4f} MRR {on['MRR@5']:.4f}")
    off, on = results["pooled"]["off"], results["pooled"]["on"]
    print(f"{'pooled':<13} off R@1 {off['R@1']:.4f} R@3 {off['R@3']:.4f} R@5 {off['R@5']:.4f} MRR {off['MRR@5']:.4f} | "
          f"on R@1 {on['R@1']:.4f} R@3 {on['R@3']:.4f} R@5 {on['R@5']:.4f} MRR {on['MRR@5']:.4f}")
    off_pairs = sum(r["pair_in_top5"] for r in incident["off"])
    on_pairs = sum(r["pair_in_top5"] for r in incident["on"])
    print(f"incident pairs in final top 5: off {off_pairs}/5, on {on_pairs}/5")
    per_q = {r["question_id"]: (r["pair_in_top5"], n["pair_in_top5"]) for r, n in zip(incident["off"], incident["on"])}
    print("incident per question (off, on):", per_q)
    print(f"VERDICT: {results['adoption']['verdict']}")
    for lq in results["losing_questions"]:
        print(f"LOSS [{lq['set']}/{lq['metric']}] {lq['question']}\n  expected={lq['expected']}\n  off={lq['off_top5']}\n  on ={lq['on_top5']}\n  trace={lq['trace_on']}")
    print(f"written: {OUT_JSON}")


if __name__ == "__main__":
    main()
