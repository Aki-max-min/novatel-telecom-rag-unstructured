"""
E13 Phase 5 - full hybrid pipeline evaluation against the REAL benchmarks.

Three arms, same FAISS assets, same graph, same metric code as
knowledge_graph/evaluate_graph_rag.py (imported, not reimplemented):

  vector_only         - Person A's index via knowledge_graph VectorRetriever (document level)
  graph_blanket(0.5)  - RRF vector=1.0 / graph=0.5 on every query, no gate, no rerank
  E13_hybrid(gated)   - query gate -> weighted RRF -> dedup -> controlled CrossEncoder rerank

plus one diagnostic arm, E13_gated_fusion_only (gate + fusion + dedup, no rerank),
to separate the gate's effect from the reranker's.

NOT tuned / held out: no threshold or rule was adjusted after seeing results;
the gate weights (0.5 / 0.15 / 0.0) are the Phase 2 values, unchanged.

Run from the repo root in an environment with faiss + sentence-transformers:
    python hybrid/evaluate_hybrid.py [output.json]   # default: hybrid/evaluation_results.json
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(REPO_ROOT)  # ingestion's paths are repo-relative

import ingestion.evaluate_retrieval as person_a  # noqa: E402
from knowledge_graph.evaluate_graph_rag import (  # noqa: E402
    GRAPH_BENCHMARK_PATH, fmt, load_benchmark, score_run,
)
from knowledge_graph.graph_augmented_retrieval import (  # noqa: E402
    GRAPH_CANDIDATES, GRAPH_SEEDS, VECTOR_DEPTH, VectorRetriever,
    graph_enhanced_search, graph_expand, load_graph_index, DEFAULT_BRIDGES,
)
from query_gate import explain_gate  # noqa: E402
from fusion import fuse_and_select  # noqa: E402
from rerank import controlled_rerank  # noqa: E402

MAX_POOL = 20
TOP_K = 5
RESULTS_PATH = Path(__file__).resolve().parent / "evaluation_results.json"


class Corpus:
    """Chunk text + chunk ids per document, from Person A's stored assets."""

    def __init__(self, metadata):
        self.chunks_by_doc = {}
        self.title_by_doc = {}
        for entry in metadata:
            self.chunks_by_doc.setdefault(entry["document_id"], []).append(entry["chunk_id"])
            self.title_by_doc[entry["document_id"]] = entry.get("title", "")

    def first_chunk(self, document_id):
        chunks = self.chunks_by_doc.get(document_id)
        return sorted(chunks)[0] if chunks else None


def to_candidate(document_id, chunk_id, score, method, category, content):
    """Common Result Schema dict."""
    return {"source": "unstructured", "record_id": chunk_id or document_id,
            "dataset": "novatel_synthetic", "category": category, "score": score,
            "retrieval_method": method, "content": content,
            "metadata": {"document_id": document_id}}


def build_candidates(question, retriever, graph_index, corpus):
    """Real vector + real graph candidates for one question, as schema dicts.

    Vector: retriever.search() (Person A's index, document-level, best chunk per doc).
    Graph : graph_expand() over the top GRAPH_SEEDS vector documents - the exact
            expansion validated in the KG evaluation.
    A graph document that is also in the vector list reuses the vector list's chunk
    record_id, so fusion sums its two RRF contributions (fusion keys on record_id).
    Graph-only documents are represented by their first chunk.
    """
    hits = retriever.search(question, depth=VECTOR_DEPTH)
    vector, vector_chunk = [], {}
    for h in hits:
        vector_chunk[h["document_id"]] = h
        vector.append(to_candidate(h["document_id"], h["chunk_id"], h["score"], "vector",
                                   h["category"], person_a.load_chunk_text(h["chunk_id"])))

    expanded = graph_expand([h["document_id"] for h in hits[:GRAPH_SEEDS]], graph_index,
                            bridges=DEFAULT_BRIDGES, limit=GRAPH_CANDIDATES)
    graph, dropped = [], 0
    for row in expanded:
        doc = row["document_id"]
        if doc in vector_chunk:
            h = vector_chunk[doc]
            chunk_id, category = h["chunk_id"], h["category"]
        else:
            chunk_id, category = corpus.first_chunk(doc), ""
        if chunk_id is None:  # document in the graph but not in the index: nothing to rerank
            dropped += 1
            continue
        graph.append(to_candidate(doc, chunk_id, row["graph_score"], "graph", category,
                                  person_a.load_chunk_text(chunk_id)))
    return vector, graph, dropped


def doc_ids(candidates):
    return [c["metadata"]["document_id"] for c in candidates]


def evaluate(name, benchmark, retriever, graph_index, corpus):
    rankings = {"vector_only": [], "graph_blanket": [], "e13_fusion_only": [], "e13_hybrid": []}
    expectations, per_question, dropped_total = [], [], 0

    for item in benchmark:
        q = item["question"]
        expected = set(item["expected_document_ids"])

        blanket = graph_enhanced_search(q, retriever, graph_index, vector_weight=1.0, graph_weight=0.5)
        vector, graph, dropped = build_candidates(q, retriever, graph_index, corpus)
        dropped_total += dropped

        gate = explain_gate(q)
        fused = fuse_and_select(vector, graph, q, top_k=MAX_POOL)
        fusion_only = fused[:TOP_K]
        final = controlled_rerank(q, fused, max_pool=MAX_POOL, top_k=TOP_K)
        if any(c["rerank_score"] is None for c in final):
            raise RuntimeError("CrossEncoder fallback triggered - refusing to report a fake rerank")

        rankings["vector_only"].append(blanket.vector_documents)
        rankings["graph_blanket"].append(blanket.fused_documents)
        rankings["e13_fusion_only"].append(doc_ids(fusion_only))
        rankings["e13_hybrid"].append(doc_ids(final))
        expectations.append(expected)
        per_question.append({
            "question_id": item.get("question_id", ""), "question": q,
            "expected": sorted(expected),
            "gate": gate["classification"], "graph_weight": gate["graph_weight"],
            "vector_top5": blanket.vector_documents[:5],
            "graph_blanket_top5": blanket.fused_documents[:5],
            "e13_fusion_only_top5": doc_ids(fusion_only),
            "e13_hybrid_top5": doc_ids(final),
            "rerank_scores": [round(c["rerank_score"], 3) for c in final],
        })

    scores = {arm: score_run(r, expectations) for arm, r in rankings.items()}
    return {"name": name, "questions": len(benchmark), "scores": scores,
            "graph_docs_without_chunks_dropped": dropped_total, "per_question": per_question}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    retriever = VectorRetriever()
    graph_index = load_graph_index()
    with open(person_a.METADATA_PATH, encoding="utf-8") as fh:
        corpus = Corpus(json.load(fh))

    runs = [
        evaluate("Main benchmark", load_benchmark(Path(person_a.BENCHMARK_PATH)),
                 retriever, graph_index, corpus),
        evaluate("Graph-dependent mini-benchmark", load_benchmark(GRAPH_BENCHMARK_PATH),
                 retriever, graph_index, corpus),
    ]

    print("===== E13 PHASE 5 — FULL HYBRID PIPELINE EVALUATION =====")
    labels = [("vector_only", "vector_only:       "),
              ("graph_blanket", "graph_blanket(0.5): "),
              ("e13_hybrid", "E13_hybrid(gated):  "),
              ("e13_fusion_only", "[diag] gate+fusion, no rerank:")]
    for run in runs:
        print(f"--- {run['name']} ({run['questions']} Q) ---")
        for key, label in labels:
            print(f"{label} {fmt(run['scores'][key])}")
        if run["graph_docs_without_chunks_dropped"]:
            print(f"(graph docs with no indexed chunk dropped from E13 arms: {run['graph_docs_without_chunks_dropped']})")

    all_q = [q for run in runs for q in run["per_question"]]
    dist = Counter(q["graph_weight"] for q in all_q)
    print(f"--- Gate weight distribution ({len(all_q)} questions total) ---")
    print(f"weight=0.5: {dist[0.5]}   weight=0.15: {dist[0.15]}   weight=0.0: {dist[0.0]}")
    print("--- Per-question gate output (for the questionable-hint review) ---")
    for run in runs:
        print(f"[{run['name']}]")
        for q in run["per_question"]:
            g = q["gate"]
            print(f"  w={q['graph_weight']:<4} personal={g['needs_personal_data']!s:<5} "
                  f"hint={g['concept_hint']!s:<30} | {q['question']}")

    payload = {"note": "Not tuned or held out. Gate thresholds unchanged from Phase 2.",
               "max_pool": MAX_POOL, "top_k": TOP_K, "runs": runs}
    results_path = Path(sys.argv[1]) if len(sys.argv) > 1 else RESULTS_PATH
    results_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"per-question results written to {results_path}")
    print("=" * 50)


if __name__ == "__main__":
    main()
