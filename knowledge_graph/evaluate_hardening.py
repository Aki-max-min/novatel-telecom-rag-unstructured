"""E13 KG hardening - Part 5: the 22-configuration comparison, run exactly as pre-declared in
docs/E13_kg_hardening_rule.md (committed before any code).

* Dev sets (NOT Person A's 42 questions): main 29 (ingestion/retrieval_benchmark.json), mini 9
  (knowledge_graph/graph_benchmark.json - the same 9 questions that evaluate_graph_rag.py's graph-dependent set and
  hybrid/evaluate_hybrid.py use, counted once) and validation 14 (the unstructured + both items of the frozen route
  benchmark, as in hybrid/evaluate_rerank_variants.py).
* Baseline = the same pipeline with the graph list disabled (vector + fusion + CrossEncoder rerank, default rerank mode).
* Every configuration uses the gate's graph weight, the resolved-RELATED_TO sibling step, and the default rerank mode;
  only the concept-candidate profile of graph_expand differs.
* Metric: document-level Recall@3 (also R@1, R@5, MRR@5). Per question: win = baseline missed top 3 and the configuration
  hits it; loss = the reverse.

Run once from the repo root in the rag-api environment:  python knowledge_graph/evaluate_hardening.py
Outputs: knowledge_graph/output_hardening/hardening_results.json (gitignored) and docs/E13_kg_hardening_results.md.
"""

import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "hybrid"))
os.chdir(REPO_ROOT)

from knowledge_graph.graph_augmented_retrieval import DEFAULT_BRIDGES, GraphIndex, graph_expand, load_graph_index  # noqa: E402
from pipeline import run_hybrid_retrieval  # noqa: E402
from rerank import _load_model  # noqa: E402
from retrievers import build_candidates, load_context  # noqa: E402

OUT_DIR = REPO_ROOT / "knowledge_graph" / "output_hardening"
RESULTS_JSON = OUT_DIR / "hardening_results.json"
RESULTS_MD = REPO_ROOT / "docs" / "E13_kg_hardening_results.md"
ROUTE_BENCH = REPO_ROOT / "hybrid" / "benchmark" / "route_benchmark.json"
HUB_FRACTIONS = (0.05, 0.10, 0.20)
MAX_DOCS = (3, 5, 10)
SETS = ("main29", "mini9", "validation14")


def grid():
    """V0 + 21 cells, in a fixed order: (name, kind, graph_kwargs)."""
    cells = [("V0", "V0", {})]
    for h in HUB_FRACTIONS:
        cells.append((f"V1 h={h}", "V1", {"hub_fraction": h}))
    for h in HUB_FRACTIONS:
        for m in MAX_DOCS:
            cells.append((f"V2 h={h} m={m}", "V2", {"hub_fraction": h, "specificity": True, "max_documents": m}))
    for h in HUB_FRACTIONS:
        for m in MAX_DOCS:
            cells.append((f"V3 h={h} m={m}", "V3", {"hub_fraction": h, "specificity": True, "max_documents": m,
                                                    "allowed_labels": ["Service", "VerificationMethod", "Tag"]}))
    return cells


class CachedScorer:
    def __init__(self, model):
        self.model, self.cache = model, {}

    def predict(self, pairs):
        missing = [p for p in pairs if p not in self.cache]
        if missing:
            for pair, score in zip(missing, self.model.predict(missing)):
                self.cache[pair] = float(score)
        return [self.cache[p] for p in pairs]


class CachedRetriever:
    """Memoises the vector search (the same for every configuration)."""

    def __init__(self, retriever):
        self.retriever, self.cache = retriever, {}

    def search(self, question, depth=10):
        key = (question, depth)
        if key not in self.cache:
            self.cache[key] = self.retriever.search(question, depth=depth)
        return self.cache[key]


def load_sets():
    def questions(path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data = data if isinstance(data, list) else data["questions"]
        return [(i["question"], set(i["expected_document_ids"])) for i in data]
    route = json.loads(ROUTE_BENCH.read_text(encoding="utf-8"))["questions"]
    validation = [(i["question"], set(i["expected_document_ids"])) for i in route
                  if i["expected_route"] in ("unstructured", "both") and i["expected_document_ids"]]
    sets = {"main29": questions("ingestion/retrieval_benchmark.json"),
            "mini9": questions("knowledge_graph/graph_benchmark.json"), "validation14": validation}
    assert [len(sets[s]) for s in SETS] == [29, 9, 14], [len(sets[s]) for s in SETS]
    return sets


def metrics(rankings, expected):
    n = len(rankings)
    def hit(r, e, k):
        return bool(set(r[:k]) & e)
    def mrr(r, e):
        return next((1 / i for i, d in enumerate(r[:5], 1) if d in e), 0.0)
    return {"R@1": sum(hit(r, e, 1) for r, e in zip(rankings, expected)) / n,
            "R@3": sum(hit(r, e, 3) for r, e in zip(rankings, expected)) / n,
            "R@5": sum(hit(r, e, 5) for r, e in zip(rankings, expected)) / n,
            "MRR@5": sum(mrr(r, e) for r, e in zip(rankings, expected)) / n}


def run_config(kwargs, enabled, sets, ctx, scorer):
    rankings = {}
    for name in SETS:
        out = []
        for question, _ in sets[name]:
            vector, graph, _ = build_candidates(question, ctx["retriever"], ctx["graph_index"], ctx["corpus"],
                                                ctx["person_a"], use_related_links=True, graph_kwargs=kwargs,
                                                graph_enabled=enabled)
            final = run_hybrid_retrieval(question, vector, graph, top_k=5, model=scorer)
            out.append([c["metadata"]["document_id"] for c in final])
        rankings[name] = out
    return rankings


def hub_audit(index, hub_fraction=0.10, best_kwargs=None):
    """Simulation: every document as a single seed. Returns, per profile, the share of candidates that share ONLY hub
    concepts (hub = df > hub_fraction x N) and same-category precision@5 / @20 (mean over seeds that have candidates)."""
    n = index.document_count
    threshold = hub_fraction * n
    docs = sorted(index.document_concepts)
    category = {d: next(iter(index.document_concepts[d].get("Category", set())), None) for d in docs}

    def is_hub(concept_key):
        label, concept = concept_key.split(":", 1)
        return index.document_frequency(label, concept) > threshold

    profiles = {"V0": {}, "V1 h=0.10": {"hub_fraction": 0.10}}
    if best_kwargs:
        profiles["V3 best"] = best_kwargs
    out = {}
    for name, kwargs in profiles.items():
        total = only_hub = 0
        p5, p20 = [], []
        for seed in docs:
            cands = graph_expand([seed], index, bridges=DEFAULT_BRIDGES, limit=20, **kwargs)
            if not cands:
                continue
            total += len(cands)
            only_hub += sum(all(is_hub(c) for c in row["shared_concepts"]) for row in cands)
            same = [category.get(row["document_id"]) == category.get(seed) for row in cands]
            p5.append(sum(same[:5]) / len(same[:5]))
            p20.append(sum(same[:20]) / len(same[:20]))
        out[name] = {"candidates": total, "share_only_hub_concepts": round(only_hub / total, 4) if total else None,
                     "same_category_p@5": round(sum(p5) / len(p5), 4) if p5 else None,
                     "same_category_p@20": round(sum(p20) / len(p20), 4) if p20 else None,
                     "seeds_with_candidates": len(p5)}
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sets = load_sets()
    ctx = load_context()
    ctx = dict(ctx, retriever=CachedRetriever(ctx["retriever"]))
    scorer = CachedScorer(_load_model())
    expected = {s: [e for _, e in sets[s]] for s in SETS}
    questions = {s: [q for q, _ in sets[s]] for s in SETS}

    base_rank = run_config({}, False, sets, ctx, scorer)
    results = {}
    for name, kind, kwargs in grid():
        rankings = run_config(kwargs, True, sets, ctx, scorer)
        row = {"kind": kind, "kwargs": kwargs, "per_set": {}, "per_question": {}}
        wins = losses = 0
        for s in SETS:
            w, l, per_q = 0, 0, []
            for q, b, c, e in zip(questions[s], base_rank[s], rankings[s], expected[s]):
                bh, ch = bool(set(b[:3]) & e), bool(set(c[:3]) & e)
                if (not bh) and ch:
                    w += 1
                    per_q.append({"question": q, "outcome": "win", "baseline_top3": b[:3], "config_top3": c[:3],
                                  "expected": sorted(e)})
                elif bh and not ch:
                    l += 1
                    per_q.append({"question": q, "outcome": "loss", "baseline_top3": b[:3], "config_top3": c[:3],
                                  "expected": sorted(e)})
            row["per_set"][s] = {"wins": w, "losses": l, "net": w - l, **metrics(rankings[s], expected[s])}
            row["per_question"][s] = per_q
            wins, losses = wins + w, losses + l
        pooled_rank = [r for s in SETS for r in rankings[s]]
        pooled_exp = [e for s in SETS for e in expected[s]]
        row["pooled"] = {"wins": wins, "losses": losses, "net": wins - losses, **metrics(pooled_rank, pooled_exp)}
        results[name] = row
        print(f"{name:<18} pooled wins={wins} losses={losses} net={wins - losses:+d}  "
              + " ".join(f"{s}:{row['per_set'][s]['net']:+d}" for s in SETS), flush=True)

    base = {s: metrics(base_rank[s], expected[s]) for s in SETS}
    base["pooled"] = metrics([r for s in SETS for r in base_rank[s]], [e for s in SETS for e in expected[s]])

    # ---- pre-declared selection and adoption (21 cells; V0 is reported, not selectable) ----
    def tie_key(item):
        name, row = item
        kw = row["kwargs"]
        max_docs = kw.get("max_documents") or 10 ** 6
        return (-row["pooled"]["net"], max_docs, -(kw.get("hub_fraction") or 0))
    cells = [(n, r) for n, r in results.items() if r["kind"] != "V0"]
    selected_name, selected = sorted(cells, key=tie_key)[0]
    p = selected["pooled"]
    min_set_net = min(selected["per_set"][s]["net"] for s in SETS)
    verdict = bool(p["net"] >= 2 and p["losses"] <= 2 and min_set_net >= -1)
    best_v3 = sorted([(n, r) for n, r in results.items() if r["kind"] == "V3"], key=tie_key)[0]

    audit = hub_audit(load_graph_index(), 0.10, best_v3[1]["kwargs"])
    OUT_DIR.mkdir(exist_ok=True)
    payload = {"rule": "docs/E13_kg_hardening_rule.md", "baseline": base, "configs": results,
               "selected": selected_name, "selected_cell": {"pooled": p, "per_set": selected["per_set"]},
               "adoption": {"verdict": "PASS" if verdict else "FAIL", "pooled_net": p["net"], "pooled_losses": p["losses"],
                            "min_single_set_net": min_set_net},
               "best_v3_cell": best_v3[0], "hub_audit": audit}
    RESULTS_JSON.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    write_markdown(payload)
    print(f"\nSELECTED: {selected_name}  pooled net {p['net']:+d} (wins {p['wins']}, losses {p['losses']}), "
          f"min single-set net {min_set_net:+d}  -> ADOPTION {'PASS' if verdict else 'FAIL'}")
    print(f"written: {RESULTS_JSON}\nwritten: {RESULTS_MD}")


def fmt(x):
    return f"{x:.4f}"


def write_markdown(r):
    base, cfgs = r["baseline"], r["configs"]
    lines = ["# E13 KG hardening - results", "",
             "Run exactly as pre-declared in `docs/E13_kg_hardening_rule.md` (22 configurations, dev sets only: main 29, mini 9, "
             "validation 14; Person A's 42 questions were not used). Raw output: `knowledge_graph/output_hardening/hardening_results.json` "
             "(gitignored). Reproduce: `python knowledge_graph/evaluate_hardening.py` in the rag-api environment.", "",
             "Baseline = same pipeline with the graph list disabled (vector + fusion + CrossEncoder, default rerank mode). "
             "Every configuration also uses the resolved-RELATED_TO sibling step and the gate's graph weight; only the concept-candidate "
             "profile of `graph_expand` differs. win = baseline missed the expected document in the top 3 and the configuration hits it; "
             "loss = the reverse.", "",
             "## Baseline (graph disabled)", "", "| set | R@1 | R@3 | R@5 | MRR@5 |", "|---|---|---|---|---|"]
    for s in list(SETS) + ["pooled"]:
        b = base[s]
        lines.append(f"| {s} | {fmt(b['R@1'])} | {fmt(b['R@3'])} | {fmt(b['R@5'])} | {fmt(b['MRR@5'])} |")
    lines += ["", "## All 22 configurations", "",
              "| config | pooled W/L/net | main29 W/L | mini9 W/L | val14 W/L | pooled R@1 | R@3 | R@5 | MRR@5 | main29 R@3 | mini9 R@3 | val14 R@3 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, row in cfgs.items():
        ps, p = row["per_set"], row["pooled"]
        lines.append(f"| {name} | {p['wins']}/{p['losses']}/{p['net']:+d} | {ps['main29']['wins']}/{ps['main29']['losses']} | "
                     f"{ps['mini9']['wins']}/{ps['mini9']['losses']} | {ps['validation14']['wins']}/{ps['validation14']['losses']} | "
                     f"{fmt(p['R@1'])} | {fmt(p['R@3'])} | {fmt(p['R@5'])} | {fmt(p['MRR@5'])} | "
                     f"{fmt(ps['main29']['R@3'])} | {fmt(ps['mini9']['R@3'])} | {fmt(ps['validation14']['R@3'])} |")
    sel, a = r["selected"], r["adoption"]
    lines += ["", "## Selected cell and adoption-rule verdict", "",
              f"Selected (highest pooled wins - losses; ties: smaller max_documents, then larger hub_fraction): **{sel}**, "
              f"pooled wins {a['pooled_net'] + a['pooled_losses']}, losses {a['pooled_losses']}, net {a['pooled_net']:+d}; "
              f"smallest single-set net {a['min_single_set_net']:+d}.", "",
              "Adoption rule: pooled net >= +2 AND pooled losses <= 2 AND no single dev set net < -1.", "",
              f"**Verdict: {a['verdict']}.**" + ("" if a["verdict"] == "PASS" else
                                                  " Negative result: the graph stays OFF by default."), "",
              "### Per-question wins and losses of the selected cell", ""]
    pq = cfgs[sel]["per_question"]
    any_row = False
    for s in SETS:
        for item in pq[s]:
            any_row = True
            lines.append(f"- [{s}] **{item['outcome'].upper()}** {item['question']}  expected={item['expected']}  "
                         f"baseline top3={item['baseline_top3']}  config top3={item['config_top3']}")
    if not any_row:
        lines.append("(none: the selected cell changed no question's top-3 outcome)")
    lines += ["", "## Hub audit (each document as a single seed, graph_expand limit 20)", "",
              "Hub = concept in more than 10% of documents. `share_only_hub_concepts` = share of candidates whose shared concepts are all hubs. "
              "Same-category precision is a rough proxy for relevance (mean over seeds that have candidates).", "",
              f"V3 best = {r['best_v3_cell']}.", "",
              "| profile | candidates | share sharing only hubs | same-category p@5 | p@20 |", "|---|---|---|---|---|"]
    for name, a_ in r["hub_audit"].items():
        lines.append(f"| {name} | {a_['candidates']} | {a_['share_only_hub_concepts']} | {a_['same_category_p@5']} | {a_['same_category_p@20']} |")
    lines += ["", "Reference simulation from the task brief: 72% (1732 of 2393) of V0 candidates share only hubs; same-category p@5 was "
              "0.38 (V0), 0.68 (hub cut), 0.72 (specific labels only)."]
    RESULTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
