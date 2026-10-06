"""
Real vector + graph candidate retrieval for the hybrid pipeline (factored out of
hybrid/evaluate_hybrid.py, behaviour unchanged).

  * vector : knowledge_graph.graph_augmented_retrieval.VectorRetriever, which wraps Person A's
             FAISS assets from ingestion.evaluate_retrieval (document level, best chunk per document)
  * graph  : knowledge_graph.graph_augmented_retrieval.graph_expand over the top GRAPH_SEEDS
             vector documents - the expansion validated in the KG evaluation

Needs an environment with faiss + sentence-transformers (e.g. the rag-api conda env). Ingestion's
paths are repo-relative, so the first load switches the working directory to the repo root.
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_context = None


class Corpus:
    """Chunk ids per document, from Person A's stored chunk metadata."""

    def __init__(self, metadata):
        self.chunks_by_doc = {}
        self.title_by_doc = {}
        for entry in metadata:
            self.chunks_by_doc.setdefault(entry["document_id"], []).append(entry["chunk_id"])
            self.title_by_doc[entry["document_id"]] = entry.get("title", "")

    def first_chunk(self, document_id):
        chunks = self.chunks_by_doc.get(document_id)
        return sorted(chunks)[0] if chunks else None


def load_context():
    """Load (once) the retriever, graph index and corpus. Returns a dict."""
    global _context
    if _context is None:
        os.chdir(REPO_ROOT)  # ingestion's paths are repo-relative
        import ingestion.evaluate_retrieval as person_a
        from knowledge_graph.graph_augmented_retrieval import VectorRetriever, load_graph_index
        with open(person_a.METADATA_PATH, encoding="utf-8") as fh:
            corpus = Corpus(json.load(fh))
        _context = {"person_a": person_a, "retriever": VectorRetriever(),
                    "graph_index": load_graph_index(), "corpus": corpus}
    return _context


def to_candidate(document_id, chunk_id, score, method, category, content, title=""):
    """Common Result Schema dict."""
    return {"source": "unstructured", "record_id": chunk_id or document_id,
            "dataset": "novatel_synthetic", "category": category, "score": score,
            "retrieval_method": method, "content": content,
            "metadata": {"document_id": document_id, "title": title}}


def build_candidates(question, retriever=None, graph_index=None, corpus=None, person_a=None):
    """Real vector + real graph candidates for one question, as schema dicts.

    Vector: retriever.search() (Person A's index, document-level, best chunk per doc).
    Graph : graph_expand() over the top GRAPH_SEEDS vector documents - the exact
            expansion validated in the KG evaluation.
    A graph document that is also in the vector list reuses the vector list's chunk
    record_id; graph-only documents are represented by their first chunk.
    Returns (vector, graph, dropped) where dropped counts graph documents with no indexed chunk.
    """
    from knowledge_graph.graph_augmented_retrieval import (
        DEFAULT_BRIDGES, GRAPH_CANDIDATES, GRAPH_SEEDS, VECTOR_DEPTH, graph_expand)
    if retriever is None:
        ctx = load_context()
        retriever, graph_index = ctx["retriever"], ctx["graph_index"]
        corpus, person_a = ctx["corpus"], ctx["person_a"]

    hits = retriever.search(question, depth=VECTOR_DEPTH)
    vector, vector_chunk = [], {}
    for h in hits:
        vector_chunk[h["document_id"]] = h
        vector.append(to_candidate(h["document_id"], h["chunk_id"], h["score"], "vector",
                                   h["category"], person_a.load_chunk_text(h["chunk_id"]), h.get("title", "")))

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
                                  person_a.load_chunk_text(chunk_id), corpus.title_by_doc.get(doc, "")))
    return vector, graph, dropped
