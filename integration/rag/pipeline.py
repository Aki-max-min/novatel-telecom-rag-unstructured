"""
query -> both existing retrievers -> RRF fusion -> compact context -> LLM.

Scope lock: only the two existing retrievers (structured SQL via
StructuredRetriever, unstructured text via the existing combined FAISS
index) feed this pipeline. No KG, ontology, document graph, or ColPali is
wired in here even if present elsewhere in the repo.
"""

import json
import sys
from pathlib import Path

import faiss
from sentence_transformers import CrossEncoder, SentenceTransformer

from integration.rag.context_builder import DEFAULT_TOP_N, build_context
from integration.rag.fuse import reciprocal_rank_fusion
from integration.rag.generate import generate_answer
from integration.rag.llm_client import OllamaClient
from integration.unstructured_adapter import to_common_result

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRUCTURED_DIR = PROJECT_ROOT / "structured"

# structured/ modules use flat (non-package) imports, e.g. `from retriever
# import StructuredRetriever` inside retriever.py itself imports
# `from data_loader import DataLoader` -- so structured/ must be on
# sys.path, same pattern structured/tests/test_retrieval.py already uses.
if str(STRUCTURED_DIR) not in sys.path:
    sys.path.insert(0, str(STRUCTURED_DIR))

from retriever import StructuredRetriever  # noqa: E402

COMBINED_INDEX_PATH = PROJECT_ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore" / "faiss.index"
COMBINED_METADATA_PATH = PROJECT_ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore" / "chunk_metadata.json"
SYNTHETIC_CHUNK_DIR = PROJECT_ROOT / "data" / "processed" / "chunks"

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

FAISS_TOP_K = 10
RERANK_TOP_K = 5


class UnstructuredSearcher:
    """
    Single-query search over the existing combined (383 synthetic + 1162
    public, 1545 total) FAISS index from E9. Reuses the same embedding and
    CrossEncoder models as ingestion/hybrid_rerank_retrieval.py.

    Deliberate, disclosed simplification: hybrid_rerank_retrieval.py's
    title/category boost used the benchmark's ground-truth expected
    category, which a live query doesn't have. This searcher is FAISS
    top-k + CrossEncoder rerank only -- no title/category signal is
    silently re-added.
    """

    def __init__(self):
        self.index = faiss.read_index(str(COMBINED_INDEX_PATH))
        with open(COMBINED_METADATA_PATH, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
        self.reranker = CrossEncoder(RERANKER_MODEL_NAME)
        self._text_cache: dict[str, str] = {}

    def _load_text(self, record: dict) -> str:
        if "text" in record:
            return record["text"]
        chunk_id = record["chunk_id"]
        if chunk_id not in self._text_cache:
            chunk_path = SYNTHETIC_CHUNK_DIR / f"{chunk_id}.json"
            with open(chunk_path, "r", encoding="utf-8") as f:
                self._text_cache[chunk_id] = json.load(f).get("text", "")
        return self._text_cache[chunk_id]

    @staticmethod
    def _dataset_label(record: dict) -> str:
        return "novatel_synthetic" if record.get("source_corpus") == "synthetic" else "trai_public"

    def search(self, query: str, faiss_top_k: int = FAISS_TOP_K, rerank_top_k: int = RERANK_TOP_K) -> list[dict]:
        query_vector = self.embedding_model.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True
        ).astype("float32")

        scores, indices = self.index.search(query_vector, faiss_top_k)

        candidates = []
        for faiss_score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            record = self.metadata[int(idx)]
            candidates.append({
                "document_id": record["document_id"],
                "chunk_id": record["chunk_id"],
                "title": record.get("title", ""),
                "category": record.get("category", ""),
                "department": record.get("department", ""),
                "customer_scope": record.get("customer_scope", ""),
                "related_ids": record.get("related_ids", []),
                "tags": record.get("tags", []),
                "text": self._load_text(record),
                "faiss_score": float(faiss_score),
                "_dataset": self._dataset_label(record),
            })

        if candidates:
            pairs = [(query, c["text"]) for c in candidates]
            ce_scores = self.reranker.predict(pairs)
            for candidate, ce_score in zip(candidates, ce_scores):
                candidate["crossencoder_score"] = float(ce_score)
                candidate["hybrid_score"] = float(ce_score)

        candidates.sort(key=lambda c: c.get("hybrid_score", c["faiss_score"]), reverse=True)
        top = candidates[:rerank_top_k]

        return [
            to_common_result(
                {k: v for k, v in c.items() if k != "_dataset"},
                dataset=c["_dataset"],
                retrieval_method="hybrid_rerank",
            )
            for c in top
        ]

    def close(self):
        pass


class StructuredSearchAdapter:
    """Pass-through -- StructuredRetriever already emits the Common Schema."""

    def __init__(self, db_path: str | None = None):
        self.retriever = StructuredRetriever(db_path=db_path)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        return self.retriever.search(query, top_k=top_k)["results"]

    def close(self):
        self.retriever.close()


class RagPipeline:
    """
    Holds both retrievers (and their loaded models) once, for reuse across
    many queries -- construct it once per process, not once per query.
    """

    def __init__(self, llm_client: OllamaClient | None = None, db_path: str | None = None):
        self.unstructured = UnstructuredSearcher()
        self.structured = StructuredSearchAdapter(db_path=db_path)
        self.llm_client = llm_client or OllamaClient()

    def run_query(self, question: str, top_n_context: int = DEFAULT_TOP_N) -> dict:
        structured_results = self.structured.search(question)
        unstructured_results = self.unstructured.search(question)

        fused = reciprocal_rank_fusion(structured_results, unstructured_results)
        context = build_context(fused, top_n=top_n_context)
        generation = generate_answer(question, context["context_text"], client=self.llm_client)

        return {
            "question": question,
            "structured_results": structured_results,
            "unstructured_results": unstructured_results,
            "fused_results": fused,
            "evidence": context["evidence"],
            "context_text": context["context_text"],
            "answer": generation["answer"],
        }

    def close(self):
        self.structured.close()
        self.unstructured.close()


def run_query(question: str, top_n_context: int = DEFAULT_TOP_N) -> dict:
    """Convenience one-off entry point (builds and tears down a pipeline).
    For more than one query, build a RagPipeline once and call run_query
    on it repeatedly -- this avoids reloading the embedding/reranker models
    per call."""
    pipeline = RagPipeline()
    try:
        return pipeline.run_query(question, top_n_context=top_n_context)
    finally:
        pipeline.close()
