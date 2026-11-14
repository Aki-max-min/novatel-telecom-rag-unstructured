"""
Read-only diagnostics (no LLM, nothing retrained or tuned) from results/perf_report/raw_answers.jsonl:

  6a  graph expansion on the 14 E14a document questions: gold document rank in B2 vs the docgraph arm, every chunk the expansion added (document, source
      category, bridge concept or RELATED_TO, relevant or not), and what displaced the gold document at rank 1;
  6b  router: every record where the router arm (and C) excluded a needed source or abstained.

    python eval/perf_report/diagnose_graph_router.py   ->   results/perf_report/diagnostics_graph_router.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h  # noqa: E402
import run_report as rr  # noqa: E402

for p in (str(h.ROOT), str(h.ROOT / "hybrid")):
    if p not in sys.path:
        sys.path.insert(0, p)
from knowledge_graph.graph_augmented_retrieval import DEFAULT_BRIDGES, GRAPH_CANDIDATES, graph_expand, load_graph_index  # noqa: E402

OUT = h.RES / "diagnostics_graph_router.json"


def doc_info() -> dict:
    meta = json.loads(rr.INDEX_META.read_text(encoding="utf-8"))
    info = {}
    for m in meta:
        info.setdefault(m["document_id"], {"category": m.get("category"), "document_type": m.get("document_type"), "corpus": m.get("corpus_label"),
                                          "title": m.get("title")})
    return info


def related_edges() -> dict:
    payload = json.loads(rr.GRAPH.read_text(encoding="utf-8"))
    key_of = {n["id"]: n["key"] for n in payload["nodes"]}
    out: dict = {}
    for e in payload["edges"]:
        if e["type"] == "RELATED_TO":
            out.setdefault(key_of[e["source"]], set()).add(key_of[e["target"]])
    return out


def rank_of(docs: list, gold: list):
    return next((i for i, d in enumerate(docs, 1) if d in gold), None)


def graph_expansion(qs, raw) -> dict:
    info, related, gi = doc_info(), related_edges(), load_graph_index()
    core_doc = [q for q in qs.values() if q["is_core"] and rr.doc_requirement(q)]
    rows, displaced = [], Counter()
    summary = {"n_questions": len(core_doc), "gold_rank_1": {"B2": 0, "docgraph": 0, "C": 0}}
    for q in core_doc:
        gold = rr.doc_requirement(q)
        b2, dg, c = raw[("B2", q["id"], 1)], raw[("docgraph", q["id"], 1)], raw[("C", q["id"], 1)]
        rb, rd, rc = rank_of(b2["doc_top10"], gold), rank_of(dg["doc_top10"], gold), rank_of(c["doc_top10"], gold)
        for name, rk in (("B2", rb), ("docgraph", rd), ("C", rc)):
            summary["gold_rank_1"][name] += rk == 1
        seeds = (dg.get("semantic") or {}).get("seeds") or []
        expanded = {r["document_id"]: r for r in graph_expand(seeds, gi, bridges=DEFAULT_BRIDGES, limit=GRAPH_CANDIDATES)} if seeds else {}
        added = []
        for chunk in (dg.get("semantic") or {}).get("added_chunks") or []:
            doc_id = chunk.rsplit("_chunk_", 1)[0]
            via_bridge = expanded.get(doc_id, {}).get("shared_concepts", [])
            via_related = sorted(s for s in seeds if doc_id in related.get(s, set()))
            added.append({"chunk": chunk, "document_id": doc_id, "source_category": info.get(doc_id, {}),
                          "via": "RELATED_TO" if via_related and not via_bridge else "bridge concept",
                          "bridge_concepts": via_bridge, "related_to_from_seeds": via_related, "relevant": doc_id in gold})
        top1_dg = dg["doc_top10"][0] if dg["doc_top10"] else None
        top1_b2 = b2["doc_top10"][0] if b2["doc_top10"] else None
        top1_added = any(a["document_id"] == top1_dg for a in added)
        lost_r1 = rb == 1 and rd != 1
        if lost_r1:
            displaced["rank-1 document in docgraph was a chunk added by the expansion" if top1_added else "rank-1 document changed without being an added chunk (RRF re-ordering of retrieved documents)"] += 1
        rows.append({"question_id": q["id"], "query": q["query"], "gold_documents": gold, "gold_rank_B2": rb, "gold_rank_docgraph": rd, "gold_rank_C": rc,
                     "B2_top3": b2["doc_top10"][:3], "docgraph_top3": dg["doc_top10"][:3], "seeds": seeds, "concept": (dg.get("semantic") or {}).get("concept"),
                     "graph_weight": (dg.get("semantic") or {}).get("graph_weight"), "n_added_chunks": len(added), "added_chunks": added,
                     "lost_rank_1": lost_r1, "docgraph_rank1_doc": top1_dg, "docgraph_rank1_was_added_by_expansion": top1_added,
                     "B2_rank1_doc": top1_b2})
    n_added = sum(r["n_added_chunks"] for r in rows)
    n_rel = sum(1 for r in rows for a in r["added_chunks"] if a["relevant"])
    summary.update({"added_chunks_total": n_added, "added_chunks_relevant": n_rel, "added_via_RELATED_TO": sum(1 for r in rows for a in r["added_chunks"] if a["via"] == "RELATED_TO"),
                    "questions_that_lost_rank_1": sum(r["lost_rank_1"] for r in rows), "why_rank_1_lost": dict(displaced),
                    "questions_with_added_chunks": sum(1 for r in rows if r["n_added_chunks"])})
    return {"summary": summary, "rows": rows}


def router_losses(qs, raw) -> list:
    rows = []
    for arm in ("router", "C"):
        for (a, qid, run), rec in raw.items():
            if a != arm or not rec.get("route"):
                continue
            q = qs[qid]
            route, rt = rec["route"]["final"], rec["route"]
            need_sql, need_docs = rr.sql_requirements(q), rr.doc_requirement(q)
            excluded = ("structured" if need_sql and route == "unstructured" else "unstructured" if need_docs and route == "structured" else
                        "both (abstained: out_of_scope)" if route == "out_of_scope" else None)
            if excluded:
                rows.append({"arm": arm, "question_id": qid, "run": run, "category": q["category"], "query": q["query"], "router": rt["router"], "router_label": rt["label"],
                             "confidence": rt["confidence"], "final_route": route, "excluded_source": excluded, "gold_documents": need_docs,
                             "gold_sql_rows": [f"{t}:{r}" for t, r in need_sql], "abstained": bool(rec.get("abstained"))})
    return rows


def main() -> None:
    qs, raw, _ = rr.load()
    out = {"note": "read-only diagnosis from saved records; retrieval is identical across runs for these arms, so run 1 is used for 6a",
           "6a_graph_expansion_core14": graph_expansion(qs, raw), "6b_router_losses": router_losses(qs, raw)}
    out["6b_summary"] = {"records": len(out["6b_router_losses"]), "by_arm": dict(Counter(r["arm"] for r in out["6b_router_losses"])),
                         "by_excluded": dict(Counter(r["excluded_source"] for r in out["6b_router_losses"])),
                         "distinct_questions": sorted({r["question_id"] for r in out["6b_router_losses"]})}
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=list), encoding="utf-8")
    s = out["6a_graph_expansion_core14"]["summary"]
    print("6a:", json.dumps(s, indent=1))
    for r in out["6a_graph_expansion_core14"]["rows"]:
        print(f"  {r['question_id']:10s} gold rank B2={r['gold_rank_B2']} docgraph={r['gold_rank_docgraph']} C={r['gold_rank_C']} added={r['n_added_chunks']} "
              f"relevant_added={sum(a['relevant'] for a in r['added_chunks'])} lost_r1={r['lost_rank_1']}")
    print("6b:", json.dumps(out["6b_summary"], indent=1))
    print("saved", OUT)


if __name__ == "__main__":
    main()
