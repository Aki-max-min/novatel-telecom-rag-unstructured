"""
E13 Phase 8b - rerank variants under the PRE-DECLARED selection rule
(docs/E13_phase8_rerank_selection_rule.md, committed before this script was run).

Variants: V0 override | V1 rrf_blend w=1.0 | V2 rrf_blend w=0.5 | V3 protect_graph.
Selection sets: main 29-Q and graph-dependent 9-Q (both already seen/used for tuning earlier).
Validation set: the 14 unstructured + both items of the frozen route benchmark.
Gate and fusion are as of Phase 8a. The CrossEncoder scores each (question, text) pair once and
the scores are shared by all four variants, so the only difference between them is the ordering rule.

Run once from the repo root in the rag-api environment:  python hybrid/evaluate_rerank_variants.py
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)

import ingestion.evaluate_retrieval as person_a  # noqa: E402
from knowledge_graph.evaluate_graph_rag import GRAPH_BENCHMARK_PATH, load_benchmark, score_run  # noqa: E402
from knowledge_graph.graph_augmented_retrieval import VectorRetriever, load_graph_index  # noqa: E402
from fusion import fuse_and_select  # noqa: E402
from rerank import _load_model, controlled_rerank  # noqa: E402
from retrievers import Corpus, build_candidates  # noqa: E402

MAX_POOL, TOP_K = 20, 5
VARIANTS = [("V0", "override", None), ("V1", "rrf_blend", 1.0),
            ("V2", "rrf_blend", 0.5), ("V3", "protect_graph", None)]
TIE_ORDER = ["V0", "V3", "V1", "V2"]  # closest to V0 first (declared in the rule)
ROUTE_BENCH = Path(__file__).resolve().parent / "benchmark" / "route_benchmark.json"
OUT = Path(__file__).resolve().parent / "evaluation_results_rerank_variants.json"


class CachedScorer:
    """Wraps the real CrossEncoder; each (question, text) pair is scored once and shared by all variants."""

    def __init__(self, model):
        self.model, self.cache, self.calls = model, {}, 0

    def predict(self, pairs):
        missing = [p for p in pairs if p not in self.cache]
        if missing:
            self.calls += len(missing)
            for pair, score in zip(missing, self.model.predict(missing)):
                self.cache[pair] = float(score)
        return [self.cache[p] for p in pairs]


def doc_ids(cands):
    return [c["metadata"]["document_id"] for c in cands]


def run_variants(questions, retriever, graph_index, corpus, scorer):
    """questions: list of (question_text, expected_set). Returns {variant: [ranked doc ids]}."""
    ranked = {v: [] for v, _, _ in VARIANTS}
    for text, _ in questions:
        vector, graph, _ = build_candidates(text, retriever, graph_index, corpus, person_a)
        pool = fuse_and_select(vector, graph, text, top_k=MAX_POOL)
        for name, mode, weight in VARIANTS:
            final = controlled_rerank(text, pool, max_pool=MAX_POOL, top_k=TOP_K, model=scorer,
                                      mode=mode, blend_weight=weight)
            ranked[name].append(doc_ids(final))
    return ranked


def hit(ranked, expected, k):
    return bool(set(ranked[:k]) & expected)


def mrr5(ranked, expected):
    for i, d in enumerate(ranked[:5], start=1):
        if d in expected:
            return 1.0 / i
    return 0.0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    retriever, graph_index = VectorRetriever(), load_graph_index()
    with open(person_a.METADATA_PATH, encoding="utf-8") as fh:
        corpus = Corpus(json.load(fh))
    scorer = CachedScorer(_load_model())

    main_q = [(i["question"], set(i["expected_document_ids"]))
              for i in load_benchmark(Path(person_a.BENCHMARK_PATH))]
    mini_q = [(i["question"], set(i["expected_document_ids"])) for i in load_benchmark(GRAPH_BENCHMARK_PATH)]
    route = json.loads(ROUTE_BENCH.read_text(encoding="utf-8"))["questions"]
    val_q = [(i["question"], set(i["expected_document_ids"])) for i in route
             if i["expected_route"] in ("unstructured", "both") and i["expected_document_ids"]]
    assert (len(main_q), len(mini_q), len(val_q)) == (29, 9, 14), (len(main_q), len(mini_q), len(val_q))

    results = {}
    for label, qs in (("main", main_q), ("mini", mini_q), ("validation", val_q)):
        ranked = run_variants(qs, retriever, graph_index, corpus, scorer)
        expected = [e for _, e in qs]
        results[label] = {}
        for name, _, _ in VARIANTS:
            if label == "validation":
                n = len(qs)
                results[label][name] = {
                    "hit@3": sum(hit(r, e, 3) for r, e in zip(ranked[name], expected)),
                    "hit@5": sum(hit(r, e, 5) for r, e in zip(ranked[name], expected)),
                    "mrr@5": round(sum(mrr5(r, e) for r, e in zip(ranked[name], expected)) / n, 4), "n": n}
            else:
                results[label][name] = score_run(ranked[name], expected)
        results[label]["_rankings"] = ranked

    # --- the pre-declared rule, applied mechanically ---
    macro = {v: round((results["main"][v]["mrr@5"] + results["mini"][v]["mrr@5"]) / 2, 4) for v, _, _ in VARIANTS}
    base = results["main"]["V0"]
    vetoed = {}
    for v, _, _ in VARIANTS:
        d3 = base["recall@3"] - results["main"][v]["recall@3"]
        d5 = base["recall@5"] - results["main"][v]["recall@5"]
        # metrics are rounded to 4 dp, so allow that rounding when testing 'more than 1/29'
        vetoed[v] = bool(d3 > 1 / 29 + 1e-4 or d5 > 1 / 29 + 1e-4)
    eligible = [v for v, _, _ in VARIANTS if not vetoed[v]]
    best = max(macro[v] for v in eligible)
    tied = [v for v in eligible if abs(macro[v] - best) < 5e-5]
    winner = min(tied, key=TIE_ORDER.index)
    v0_hit3 = results["validation"]["V0"]["hit@3"]
    drop = v0_hit3 - results["validation"][winner]["hit@3"]
    validation_ok = (winner == "V0") or drop < 1
    adopted = winner if validation_ok else "V0"

    print("===== E13 PHASE 8b - rerank variants (pre-declared rule) =====")
    print(f"CrossEncoder pair scores computed: {scorer.calls} (shared by all variants)")
    print(f"{'variant':<8}{'main R@1 R@3 R@5 MRR@5':<34}{'mini R@1 R@3 R@5 MRR@5':<34}{'macro':<8}{'vetoed':<8}validation hit@3 / hit@5 / MRR@5")
    for v, mode, w in VARIANTS:
        m, n_, val = results["main"][v], results["mini"][v], results["validation"][v]
        print(f"{v:<8}{m['recall@1']:.4f} {m['recall@3']:.4f} {m['recall@5']:.4f} {m['mrr@5']:.4f}   "
              f"{n_['recall@1']:.4f} {n_['recall@3']:.4f} {n_['recall@5']:.4f} {n_['mrr@5']:.4f}   "
              f"{macro[v]:<8.4f}{str(vetoed[v]):<8}{val['hit@3']}/14 / {val['hit@5']}/14 / {val['mrr@5']:.4f}")
    print(f"winner by rule: {winner}   validation check: {'pass' if validation_ok else 'FAIL'} "
          f"(V0 hit@3 {v0_hit3}/14, {winner} hit@3 {results['validation'][winner]['hit@3']}/14)   ADOPTED: {adopted}")

    OUT.write_text(json.dumps({
        "rule": "docs/E13_phase8_rerank_selection_rule.md", "macro_mrr@5": macro, "vetoed": vetoed,
        "winner_by_rule": winner, "validation_check_passed": validation_ok, "adopted": adopted,
        "results": results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"written to {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
