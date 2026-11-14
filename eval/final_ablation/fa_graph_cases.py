"""
Graph-merge diagnostics with CrossEncoder scores (no LLM calls): for every document question, re-runs the document search exactly as the harness
does (plain = B2 behaviour, and with each graph arm's layer; retrieval is deterministic, verified per arm in metrics.json) and records the
CrossEncoder score of every top-10 chunk. For each question whose gold rank got WORSE or was LOST versus B2 it lists the chunks above the gold with
their scores, so that "the gold rank can only get worse when the CrossEncoder itself scores an added chunk higher" can be checked case by case.

    FA_EXPERIMENT=graph_merge_fix .venv_colpali/Scripts/python.exe eval/final_ablation/fa_graph_cases.py

Writes results/<experiment>/graph_cases.md (+ .json). Also cross-checks that the re-run top-10 chunk lists equal the stored run-1 records.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness_fa as fa  # noqa: E402

h = fa.h
import run_report as rr  # noqa: E402


def search_scored(rig, query, layer):
    """top-10 as the harness sees it (common results), with document id and CrossEncoder score per chunk."""
    rig.pipeline.unstructured.exclude_scifact = True
    top = rig.pipeline.unstructured.search(query, faiss_top_k=10, rerank_top_k=10, semantic=layer)
    out = []
    for r in top:
        md = r.get("metadata") or {}
        out.append({"chunk": r["record_id"], "doc": md.get("provenance", {}).get("document_id") or r["record_id"], "ce": md.get("crossencoder_score", r.get("score")),
                    "added": bool(md.get("semantic_added"))})
    return out


def main() -> None:
    qs = {q["id"]: q for q in h.load_questions()}
    raw, _ = fa.load_reused(check_counts=False, arms=["B2"])
    for r in h.read_jsonl(fa.RAW):
        raw[(r["arm"], r["id"], r["run"])] = r
    arms = [a for a in fa.GRAPH_ARMS if any(k[0] == a for k in raw)]
    rig = fa.Rig()
    out = {"arms": {}, "rerun_matches_stored_run1": {}}
    for arm in arms:
        layer = rig.layers[arm]
        cases, mismatches, n = [], [], 0
        for qid, q in qs.items():
            gold = rr.doc_requirement(q)
            if not gold:
                continue
            plain = search_scored(rig, q["query"], None)
            withg = search_scored(rig, q["query"], layer)
            stored = raw.get((arm, qid, 1))
            if stored is not None:
                n += 1
                if [x["chunk"] for x in withg] != stored["doc_top10_chunks"]:
                    mismatches.append(qid)
            rank_b2 = next((i for i, x in enumerate(_docs(plain), 1) if x in gold), None)
            rank_arm = next((i for i, x in enumerate(_docs(withg), 1) if x in gold), None)
            if rank_b2 is None or (rank_arm is not None and rank_arm <= rank_b2):
                continue
            gold_chunk = next((x for x in withg if x["doc"] in gold), None) or next((x for x in plain if x["doc"] in gold), None)
            above = withg[: (rank_arm - 1) if rank_arm else len(withg)]
            above_docs, seen = [], set()
            for x in above:
                if x["doc"] not in seen:
                    seen.add(x["doc"]); above_docs.append(x)
            cases.append({"id": qid, "category": q["category"], "gold": gold, "gold_rank_B2": rank_b2, "gold_rank_arm": rank_arm,
                          "gold_best_chunk": gold_chunk, "docs_above_gold": above_docs,
                          "all_above_have_higher_ce": all((x["ce"] or 0) >= (gold_chunk["ce"] or 0) for x in above_docs) if gold_chunk else None,
                          "added_docs_above_gold": [x["doc"] for x in above_docs if x["added"]]})
        out["arms"][arm] = cases
        out["rerun_matches_stored_run1"][arm] = {"doc_questions_checked": n, "mismatches": mismatches}
    (fa.RES / "graph_cases.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    L = ["# Gold-rank regressions with CrossEncoder scores (run 1 retrieval re-run without the LLM)", "",
         "A case is a document question whose gold document ranks worse with the graph arm than in the plain B2 search (or leaves the top 10). "
         "'ce' = CrossEncoder score against the original question; 'added' = the chunk joined the pool through the graph. With the fixed merge every document "
         "above the gold must have a higher CrossEncoder score than the gold's best chunk (checked in the last column).", ""]
    for arm, cases in out["arms"].items():
        chk = out["rerun_matches_stored_run1"][arm]
        L += [f"## {arm}: {len(cases)} regression case(s); re-run top-10 equals the stored run-1 record on {chk['doc_questions_checked'] - len(chk['mismatches'])} of {chk['doc_questions_checked']} document questions"
              + (f" (mismatches: {chk['mismatches']})" if chk["mismatches"] else ""), "",
              "| id | cat | gold | rank B2 -> arm | gold best chunk (ce) | documents above the gold (doc: ce, added?) | all above have higher ce? |", "|---|---|---|---|---|---|---|"]
        for c in cases:
            g = c["gold_best_chunk"]
            L.append(f"| {c['id']} | {c['category']} | {c['gold']} | {c['gold_rank_B2']} -> {c['gold_rank_arm']} | {g['chunk'] if g else '-'} ({g['ce']:.3f}) | " if g else
                     f"| {c['id']} | {c['category']} | {c['gold']} | {c['gold_rank_B2']} -> {c['gold_rank_arm']} | - | ")
            L[-1] += "; ".join(f"{x['doc']}: {x['ce']:.3f}{', added' if x['added'] else ''}" for x in c["docs_above_gold"]) + f" | {c['all_above_have_higher_ce']} |"
        L.append("")
    (fa.RES / "graph_cases.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


def _docs(rows):
    docs = []
    for x in rows:
        if x["doc"] not in docs:
            docs.append(x["doc"])
    return docs


if __name__ == "__main__":
    main()
