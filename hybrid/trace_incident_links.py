"""
DIAGNOSTIC ONLY (no behaviour change): where does the partner document of an incident/RCA pair sit at each pipeline stage?

For questions IL1..IL5 of hybrid/benchmark/incident_link_check.json (links ON), prints for BOTH documents of the pair:
  1. vector top-10 (document-level hits)         2. graph candidate list (linked neighbours first, then concept candidates)
  3. after fusion (fuse_and_select, dedup, gate weight applied)        4. inside the rerank pool (cap = 20, by fusion order)
  5. after the final rerank (default mode rrf_blend: fusion rank + rerank rank)  -> final top 5
and says at which stage a document that is missing from the final top 5 is lost. Writes docs/E13_incident_link_trace.md.

Run in the rag-api environment:  python hybrid/trace_incident_links.py [IL1 IL4 ...]   (default: the two misses IL1 and IL4)
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

from fusion import fuse_and_select  # noqa: E402
from query_gate import classify_query, graph_weight  # noqa: E402
from rerank import DEFAULT_BLEND_WEIGHT, DEFAULT_RERANK_MODE, _load_model, controlled_rerank  # noqa: E402
from retrievers import build_candidates, load_context  # noqa: E402

CHECK = Path(__file__).resolve().parent / "benchmark" / "incident_link_check.json"
OUT = REPO_ROOT / "docs" / "E13_incident_link_trace.md"
MAX_POOL = 20


def doc_of(c):
    return c["metadata"]["document_id"]


def position(docs, target):
    return docs.index(target) + 1 if target in docs else None


def fmt(pos, total=None):
    return "absent" if pos is None else (f"rank {pos}" + (f" of {total}" if total else ""))


def trace(item, ctx, scorer):
    question, pair = item["question"], item["pair"]
    vector, graph, _ = build_candidates(question, ctx["retriever"], ctx["graph_index"], ctx["corpus"],
                                        ctx["person_a"], use_related_links=True)
    weight = graph_weight(classify_query(question))
    vec_docs, graph_docs = [doc_of(c) for c in vector], [doc_of(c) for c in graph]
    fused = fuse_and_select(vector, graph, question, top_k=MAX_POOL)
    fused_docs = [doc_of(c) for c in fused]
    pool = sorted(fused, key=lambda c: c["fusion_score"], reverse=True)[:MAX_POOL]
    pool_docs = [doc_of(c) for c in pool]
    ranked = controlled_rerank(question, fused, max_pool=MAX_POOL, top_k=MAX_POOL, model=scorer)
    final_docs = [doc_of(c) for c in ranked]
    by_doc = {doc_of(c): c for c in ranked}
    top5 = final_docs[:5]

    lines = [f"### {item['question_id']}: {question}", "",
             f"- gate graph weight: **{weight}** ({'graph list EXCLUDED from fusion' if weight == 0 else 'graph list enters fusion'})",
             f"- vector top-10: {vec_docs}", f"- graph candidates (linked neighbours first): {graph_docs}",
             f"- fusion output (document level, {len(fused_docs)} docs): {fused_docs}",
             f"- final top 5 ({DEFAULT_RERANK_MODE}, w={DEFAULT_BLEND_WEIGHT}): {top5}", "",
             "| document | vector top-10 | graph list | after fusion | in rerank pool (cap 20) | rerank-only rank | final blend rank | in final top 5 | lost at |",
             "|---|---|---|---|---|---|---|---|---|"]
    verdicts = []
    for doc in pair:
        in_vec, in_graph = position(vec_docs, doc), position(graph_docs, doc)
        in_fused, in_pool = position(fused_docs, doc), position(pool_docs, doc)
        c = by_doc.get(doc)
        rr = c["rank_rerank"] if c else None
        final_pos = position(final_docs, doc)
        in_top5 = final_pos is not None and final_pos <= 5
        if in_top5:
            lost = "-"
        elif in_vec is None and in_graph is None:
            lost = "never retrieved (not in vector top-10 nor in the graph list)"
        elif in_fused is None and in_vec is None and weight == 0:
            lost = ("FUSION INPUT: the gate set graph weight 0.0, so the whole graph list (including this linked document, "
                    f"graph rank {in_graph}) was excluded before fusion")
        elif in_fused is None:
            lost = "FUSION/dedup (retrieved, not in the fused list)"
        elif in_pool is None:
            lost = "rerank pool cap"
        else:
            lost = (f"final rerank (blend rank {final_pos}: fusion rank {c['rank_fusion']}, rerank-only rank {rr}; "
                    f"cut at top 5)")
        verdicts.append((doc, lost))
        lines.append(f"| {doc} | {fmt(in_vec, len(vec_docs))} | {fmt(in_graph, len(graph_docs))} | {fmt(in_fused, len(fused_docs))} | "
                     f"{fmt(in_pool, len(pool_docs))} | {fmt(rr, len(ranked))} | {fmt(final_pos, len(ranked))} | "
                     f"{'yes' if in_top5 else 'NO'} | {lost} |")
    lines.append("")
    for doc, lost in verdicts:
        if lost != "-":
            lines.append(f"**{doc} is lost at: {lost}.**")
    return lines, verdicts


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    wanted = set(sys.argv[1:]) or {"IL1", "IL4"}
    items = [i for i in json.loads(CHECK.read_text(encoding="utf-8"))["questions"] if i["question_id"] in wanted]
    ctx = load_context()

    class Scorer:
        def __init__(self, model):
            self.model, self.cache = model, {}

        def predict(self, pairs):
            missing = [p for p in pairs if p not in self.cache]
            if missing:
                for pair, score in zip(missing, self.model.predict(missing)):
                    self.cache[pair] = float(score)
            return [self.cache[p] for p in pairs]

    scorer = Scorer(_load_model())
    doc = ["# E13 incident-link trace (diagnostic only)", "",
           "Generated by `hybrid/trace_incident_links.py` (no behaviour change; same functions as the pipeline). Links ON, graph weight from the gate, "
           f"rerank mode `{DEFAULT_RERANK_MODE}`. Mechanism check on five INC/RCA pairs; not evidence of generalisation.", ""]
    for item in items:
        lines, _ = trace(item, ctx, scorer)
        doc += lines + [""]
        print("\n".join(lines) + "\n")
    doc += ["### Gate graph weight for all five incident questions", "",
            "| question | concept hint | graph weight |", "|---|---|---|"]
    for item in json.loads(CHECK.read_text(encoding="utf-8"))["questions"]:
        c = classify_query(item["question"])
        doc.append(f"| {item['question_id']} | {c['concept_hint']} | {graph_weight(c)} |")
    doc += ["", "A weight of 0.0 excludes the graph list from fusion entirely (hybrid/fusion.py), so a resolved RELATED_TO link only "
            "matters for questions whose gate weight is above 0. That is why the earlier links-ON vs links-OFF check (3/5 vs 3/5) could "
            "not move those questions."]
    OUT.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
