"""
Experiments of the KG-fixes task (docs/E13_kg_fixes.md; rules pre-declared there and committed before any run).

    python hybrid/evaluate_fixes.py step2    # links: use_related_links True vs False
    python hybrid/evaluate_fixes.py step4    # category-tag leak: exclude_category_tags False vs True
    python hybrid/evaluate_fixes.py step5    # blend: rrf_blend w=1.0 vs CrossEncoder-only order
    python hybrid/evaluate_fixes.py step6    # graph profile: legacy graph_expand vs hardened (hub_fraction 0.05, max 3)

Dev sets only: main 29, mini 9, validation 14 (52 questions); Person A's 42 are never used. Graph and links ON in every arm.
The "current state" arm is read from the live pipeline/rerank constants (USE_RELATED_LINKS, GRAPH_KWARGS, DEFAULT_RERANK_MODE),
so a later step measures against the state the earlier steps accepted. Run in the rag-api environment (models cached locally).
Raw results go to knowledge_graph/output_hardening/fixes_<step>.json (gitignored).
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

import pipeline  # noqa: E402
import rerank  # noqa: E402
from knowledge_graph.evaluate_hardening import CachedRetriever, CachedScorer, SETS, load_sets, metrics  # noqa: E402
from fusion import fuse_and_select  # noqa: E402
from rerank import _load_model, controlled_rerank  # noqa: E402
from retrievers import build_candidates, link_candidates_for, load_context  # noqa: E402

INCIDENT = REPO_ROOT / "hybrid" / "benchmark" / "incident_link_check.json"
OUT_DIR = REPO_ROOT / "knowledge_graph" / "output_hardening"
POOL = 20


def current_state():
    return {"use_related_links": getattr(pipeline, "USE_RELATED_LINKS", True),
            "graph_kwargs": dict(getattr(pipeline, "GRAPH_KWARGS", {})),
            "mode": rerank.DEFAULT_RERANK_MODE}


def arms_for(step):
    cur = current_state()
    if step == "step2":
        return ("A: use_related_links=True (before)", dict(cur, use_related_links=True),
                "B: use_related_links=False (after)", dict(cur, use_related_links=False))
    if step == "step4":
        kw = dict(cur["graph_kwargs"])
        return ("A: current graph profile", dict(cur, graph_kwargs=dict(kw, exclude_category_tags=False)),
                "B: exclude category-code tags ^c\\d\\d$", dict(cur, graph_kwargs=dict(kw, exclude_category_tags=True)))
    if step == "step5":
        return ("A: rrf_blend w=1.0 (current)", dict(cur, mode="rrf_blend"),
                "B: CrossEncoder-only order (override)", dict(cur, mode="override"))
    if step == "step6":
        return ("A: legacy graph_expand", dict(cur, graph_kwargs={}),
                "B: hardened (hub_fraction=0.05, specificity, max_documents=3)",
                dict(cur, graph_kwargs={"hub_fraction": 0.05, "specificity": True, "max_documents": 3}))
    raise SystemExit(f"unknown step {step}")


class Runner:
    def __init__(self):
        self.ctx = load_context()
        self.ctx = dict(self.ctx, retriever=CachedRetriever(self.ctx["retriever"]))
        self.scorer = CachedScorer(_load_model())

    def pool_for(self, question, cfg):
        c = self.ctx
        vector, graph, _ = build_candidates(question, c["retriever"], c["graph_index"], c["corpus"], c["person_a"],
                                            use_related_links=cfg["use_related_links"], graph_kwargs=cfg["graph_kwargs"] or None,
                                            graph_enabled=True)
        links = link_candidates_for(vector, c["graph_index"], c["corpus"], c["person_a"].load_chunk_text)
        fused = fuse_and_select(vector, graph, question, top_k=POOL, link_candidates=links, link_weight=pipeline.LINK_WEIGHT)
        return vector, fused

    def ranked(self, question, cfg, top_k=5):
        vector, fused = self.pool_for(question, cfg)
        out = controlled_rerank(question, fused, max_pool=POOL, top_k=top_k, model=self.scorer, mode=cfg["mode"])
        return vector, fused, out


def hit(top, expected, k):
    return bool(set(top[:k]) & expected)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    label_a, cfg_a, label_b, cfg_b = arms_for(step)
    sets = load_sets()
    run = Runner()
    d = lambda cs: [c["metadata"]["document_id"] for c in cs]  # noqa: E731

    tops = {"A": {}, "B": {}}
    detail = {"A": {}, "B": {}}
    for arm, cfg in (("A", cfg_a), ("B", cfg_b)):
        for s in SETS:
            rows = []
            for q, e in sets[s]:
                vector, fused, out = run.ranked(q, cfg, top_k=POOL)       # full pool order; top-5 = first 5
                rows.append((d(out), d(vector), d(fused), out))
            tops[arm][s] = [r[0] for r in rows]
            detail[arm][s] = rows

    print(f"===== {step}: dev sets (52 questions), graph and links ON =====")
    print("A =", label_a, cfg_a); print("B =", label_b, cfg_b)
    result = {"arms": {"A": label_a, "B": label_b}, "cfg": {"A": cfg_a, "B": cfg_b}, "metrics": {}, "changes": []}
    losses = {1: 0, 3: 0, 5: 0}; gains = {1: 0, 3: 0, 5: 0}
    for s in SETS:
        exp = [e for _, e in sets[s]]
        qs = [q for q, _ in sets[s]]
        for arm in ("A", "B"):
            m = metrics([t[:5] for t in tops[arm][s]], exp)
            result["metrics"].setdefault(arm, {})[s] = m
        for q, e, ta, tb in zip(qs, exp, tops["A"][s], tops["B"][s]):
            for k in (1, 3, 5):
                ha, hb = hit(ta, e, k), hit(tb, e, k)
                if ha and not hb:
                    losses[k] += 1; result["changes"].append({"set": s, "k": k, "kind": "LOSS", "q": q, "expected": sorted(e), "A": ta[:5], "B": tb[:5]})
                if hb and not ha:
                    gains[k] += 1; result["changes"].append({"set": s, "k": k, "kind": "GAIN", "q": q, "expected": sorted(e), "A": ta[:5], "B": tb[:5]})
    pooled = {}
    for arm in ("A", "B"):
        allt = [t[:5] for s in SETS for t in tops[arm][s]]
        alle = [e for s in SETS for _, e in sets[s]]
        pooled[arm] = metrics(allt, alle)
    result["metrics"]["pooled"] = pooled

    for s in list(SETS) + ["pooled"]:
        ma = result["metrics"]["A"][s] if s != "pooled" else pooled["A"]
        mb = result["metrics"]["B"][s] if s != "pooled" else pooled["B"]
        print(f"{s:<13} A R@1 {ma['R@1']:.4f} R@3 {ma['R@3']:.4f} R@5 {ma['R@5']:.4f} MRR@5 {ma['MRR@5']:.4f} | "
              f"B R@1 {mb['R@1']:.4f} R@3 {mb['R@3']:.4f} R@5 {mb['R@5']:.4f} MRR@5 {mb['MRR@5']:.4f}")
    print(f"losses (A hits, B does not): R@1 {losses[1]}  R@3 {losses[3]}  R@5 {losses[5]}   | gains: R@1 {gains[1]}  R@3 {gains[3]}  R@5 {gains[5]}")
    for ch in result["changes"]:
        print(f"  {ch['kind']} @{ch['k']} [{ch['set']}] {ch['q'][:90]}\n      expected={ch['expected']}\n      A top5={ch['A']}\n      B top5={ch['B']}")

    # incident pairs (mechanism check)
    items = json.loads(INCIDENT.read_text(encoding="utf-8"))["questions"]
    inc = {}
    for arm, cfg in (("A", cfg_a), ("B", cfg_b)):
        inc[arm] = []
        for item in items:
            _, _, out = run.ranked(item["question"], cfg, top_k=5)
            inc[arm].append(set(item["pair"]) <= set(d(out)))
    result["incident"] = {"A": inc["A"], "B": inc["B"]}
    print(f"incident pairs in final top 5: A {sum(inc['A'])}/5 {inc['A']}  B {sum(inc['B'])}/5 {inc['B']}")

    no_loss = losses[1] == 0 and losses[3] == 0 and losses[5] == 0
    any_gain = (gains[1] + gains[3] + gains[5]) > 0
    gain_35 = (gains[3] + gains[5]) > 0
    inc_ok = sum(inc["B"]) >= sum(inc["A"])
    if step == "step2":
        verdict, keep = "KEEP B" if no_loss else "REVERT (A stays)", no_loss
    elif step == "step4":
        verdict, keep = ("KEEP B" if (no_loss and gain_35) else "LEAVE UNCHANGED (A stays)"), (no_loss and gain_35)
    else:
        verdict, keep = ("ADOPT B" if (no_loss and any_gain and inc_ok) else "KEEP A"), (no_loss and any_gain and inc_ok)
    result["rule"] = {"no_loss_at_1_3_5": no_loss, "any_gain": any_gain, "gain_at_3_or_5": gain_35, "incident_not_worse": inc_ok,
                      "verdict": verdict}
    print("RULE:", result["rule"])

    if step == "step5":
        extra = {"gold_not_vector_hits": [], "pushed_out": []}
        for s in SETS:
            for (q, e), (ta, va, fa, oa), (tb, vb, fb, ob) in zip(sets[s], detail["A"][s], detail["B"][s]):
                for g in sorted(e - set(va)):
                    extra["gold_not_vector_hits"].append({"set": s, "q": q[:70], "gold": g,
                                                          "in_pool": g in ta, "rank_A": ta.index(g) + 1 if g in ta else None,
                                                          "rank_B": tb.index(g) + 1 if g in tb else None})
                vset = set(va)
                by_a = {c["metadata"]["document_id"]: c for c in oa}
                for doc, c in by_a.items():
                    if doc not in vset and c["rank_rerank"] <= 5 and ta.index(doc) + 1 > 5:
                        extra["pushed_out"].append({"set": s, "q": q[:70], "doc": doc, "rerank_only_rank": c["rank_rerank"],
                                                    "rank_A": ta.index(doc) + 1, "rank_B": tb.index(doc) + 1 if doc in tb else None,
                                                    "is_gold": doc in e})
        g = extra["gold_not_vector_hits"]
        print(f"expected documents that are not vector hits: {len(g)}; in the pool: {sum(x['in_pool'] for x in g)}; "
              f"in the final top 5: arm A {sum((x['rank_A'] or 99) <= 5 for x in g)}, arm B {sum((x['rank_B'] or 99) <= 5 for x in g)}")
        for x in g: print("   ", x)
        po = extra["pushed_out"]
        print(f"appended documents in the CrossEncoder top 5 that the blend pushed out (arm A): {len(po)}; "
              f"in arm B top 5: {sum((x['rank_B'] or 99) <= 5 for x in po)}; gold among them: {sum(x['is_gold'] for x in po)}")
        for x in po: print("   ", x)
        result["extra"] = extra

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"fixes_{step}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=list), encoding="utf-8")
    print("written:", OUT_DIR / f"fixes_{step}.json")


if __name__ == "__main__":
    main()
