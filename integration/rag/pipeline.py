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

from integration.corpus_labels import corpus_label, count_scifact, dataset_label, is_scifact
from integration.rag.context_builder import DEFAULT_TOP_N, build_context
from integration.rag.fuse import reciprocal_rank_fusion
from integration.rag.generate import generate_answer
from integration.rag.llm_client import OllamaClient
from integration.rag.rag_config import RagConfig
from integration.structured_guard import guarded_structured_search
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
    Single-query search over the existing combined FAISS index from E9: 1,545
    chunks = 258 NovaTel synthetic + 125 SciFact (an external benchmark that was
    built into the index, tagged "synthetic" there) + 1,162 public TRAI chunks.
    Reuses the same embedding and CrossEncoder models as
    ingestion/hybrid_rerank_retrieval.py.

    exclude_scifact (default True): SciFact chunks are dropped at serving time (the
    index file itself is untouched). The FAISS search is over-fetched by the number
    of SciFact chunks so the candidate pool still holds `faiss_top_k` real
    candidates; when no SciFact chunk is in the top results the output is identical
    to the unfiltered search.

    Deliberate, disclosed simplification: hybrid_rerank_retrieval.py's
    title/category boost used the benchmark's ground-truth expected
    category, which a live query doesn't have. This searcher is FAISS
    top-k + CrossEncoder rerank only -- no title/category signal is
    silently re-added.
    """

    def __init__(self, exclude_scifact: bool = True):
        self.exclude_scifact = exclude_scifact
        self.index = faiss.read_index(str(COMBINED_INDEX_PATH))
        with open(COMBINED_METADATA_PATH, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        self.n_scifact_chunks = count_scifact(self.metadata)
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
        return dataset_label(record)

    def search(self, query: str, faiss_top_k: int = FAISS_TOP_K, rerank_top_k: int = RERANK_TOP_K,
               semantic=None) -> list[dict]:
        """semantic: optional integration.rag.semantic_layer.SemanticLayer. None (default) = the original E14 path,
        the same behaviour as before the layer existed."""
        search_text = query
        semantic_info = None
        if semantic is not None:
            search_text, semantic_info = semantic.normalise_query(query)
        query_vector = self.embedding_model.encode(
            [search_text], convert_to_numpy=True, normalize_embeddings=True
        ).astype("float32")

        fetch_k = faiss_top_k + (self.n_scifact_chunks if self.exclude_scifact else 0)
        scores, indices = self.index.search(query_vector, min(fetch_k, self.index.ntotal))

        candidates = []
        for faiss_score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            record = self.metadata[int(idx)]
            if self.exclude_scifact and is_scifact(record):
                continue
            if len(candidates) >= faiss_top_k:
                break
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
                "corpus_label": corpus_label(record),
                "_dataset": self._dataset_label(record),
            })

        if candidates:
            pairs = [(query, c["text"]) for c in candidates]
            ce_scores = self.reranker.predict(pairs)
            for candidate, ce_score in zip(candidates, ce_scores):
                candidate["crossencoder_score"] = float(ce_score)
                candidate["hybrid_score"] = float(ce_score)

        candidates.sort(key=lambda c: c.get("hybrid_score", c["faiss_score"]), reverse=True)
        if semantic is not None:
            candidates = self._semantic_merge(query, candidates, semantic, semantic_info)
        top = candidates[:rerank_top_k]

        return [
            to_common_result(
                {k: v for k, v in c.items() if k != "_dataset"},
                dataset=c["_dataset"],
                retrieval_method="hybrid_rerank",
            )
            for c in top
        ]

    def _candidate_from_record(self, record: dict, faiss_score: float) -> dict:
        return {
            "document_id": record["document_id"], "chunk_id": record["chunk_id"], "title": record.get("title", ""),
            "category": record.get("category", ""), "department": record.get("department", ""),
            "customer_scope": record.get("customer_scope", ""), "related_ids": record.get("related_ids", []),
            "tags": record.get("tags", []), "text": self._load_text(record), "faiss_score": faiss_score,
            "corpus_label": corpus_label(record), "_dataset": self._dataset_label(record),
        }

    def _semantic_merge(self, query: str, candidates: list[dict], semantic, info: dict | None) -> list[dict]:
        """One-hop graph expansion (see integration/rag/semantic_layer.py). Seeds = top reranked documents; their graph neighbours JOIN the
        candidate pool and are scored by the CrossEncoder against the ORIGINAL question. The final order is the CrossEncoder score alone
        (hybrid_score, descending; ties broken by chunk_id), so an added chunk ranks above an existing one only if the CrossEncoder scores it
        higher, and the relative order of the original candidates never changes. graph_weight is only an on/off switch here: > 0 means
        the graph may add candidates (the query gate's decision); the value is kept in the "semantic" trace.

        Until 2026-11-11 this method re-ranked the pool by weighted RRF: 1/(RRF_K + rank) for every chunk plus graph_weight/(RRF_K + graph_rank)
        for chunks of a graph-list document. With RRF_K = 60 the base scores are nearly flat, so any graph-list chunk passed the CrossEncoder's
        best chunk from rank 11 (weight 0.15) or rank 61 (weight 0.5) whatever its own score (Person B's analysis of the v3 docgraph arm; see
        integration/tests/test_semantic_merge_order.py). Every graph result measured before that date (v3, v4, the KG-hardening and link
        evaluations) was produced with that merge."""
        if not hasattr(self, "_chunks_by_doc"):
            self._chunks_by_doc: dict[str, list[int]] = {}
            for i, rec in enumerate(self.metadata):
                self._chunks_by_doc.setdefault(rec["document_id"], []).append(i)

        seeds: list[str] = []
        for c in candidates:
            if c["document_id"] not in seeds:
                seeds.append(c["document_id"])
            if len(seeds) >= semantic.seed_documents:   # Person B's GRAPH_SEEDS
                break
        neighbours = semantic.neighbours(seeds, set(self._chunks_by_doc))
        graph_weight = (info or {}).get("graph_weight", 0.0)
        if graph_weight <= 0.0:
            neighbours = []  # the query gate says the graph should not influence this question

        in_pool = {c["chunk_id"] for c in candidates}
        added = []
        for doc in neighbours:
            for pos in sorted(self._chunks_by_doc[doc])[:semantic.max_chunks_per_doc]:
                rec = self.metadata[pos]
                if self.exclude_scifact and is_scifact(rec):
                    continue
                if rec["chunk_id"] not in in_pool:
                    added.append(self._candidate_from_record(rec, 0.0))
        if added:
            scores = self.reranker.predict([(query, c["text"]) for c in added])
            for c, sc in zip(added, scores):
                c["crossencoder_score"] = float(sc)
                c["hybrid_score"] = float(sc)
                c["semantic_added"] = True
        pool = candidates + added
        pool.sort(key=lambda c: (-c["hybrid_score"], c["chunk_id"]))     # CrossEncoder score alone; stable, tie-break by chunk id
        for c in pool:
            c["semantic"] = {"concept": (info or {}).get("concept"), "seeds": seeds, "neighbour_docs": neighbours, "graph_weight": graph_weight,
                             "added_by_graph": bool(c.get("semantic_added"))}
        return pool

    def close(self):
        pass


class StructuredSearchAdapter:
    """Pass-through -- StructuredRetriever already emits the Common Schema.

    The only addition is integration/structured_guard.py: a customer-scoped lookup on a table with no `customer_id` column
    (cdr, recharge_transactions, sim_inventory are keyed by msisdn) used to raise sqlite3.OperationalError and end the
    question. Now such a lookup is run through the customer's msisdn (customer_master), or reported as not executable.
    `last_status` holds the outcome of the latest call: {"executed", "route", "reason", ...}. For every query that worked
    before, the results are exactly the retriever's own.
    """

    def __init__(self, db_path: str | None = None):
        self.retriever = StructuredRetriever(db_path=db_path)
        self.last_status: dict = {"executed": True, "route": "direct", "reason": None}

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        guarded = guarded_structured_search(self.retriever, query, top_k)
        self.last_status = guarded.status
        return guarded.results

    def close(self):
        self.retriever.close()


class RagPipeline:
    """
    Holds both retrievers (and their loaded models) once, for reuse across
    many queries -- construct it once per process, not once per query.
    """

    def __init__(self, llm_client: OllamaClient | None = None, db_path: str | None = None,
                 config: RagConfig | None = None):
        """config: RagConfig (integration/rag/rag_config.py). The default RagConfig() reproduces the E14a behaviour:
        shared 6-block context budget, no semantic layer."""
        self.config = config or RagConfig()
        self.unstructured = UnstructuredSearcher(exclude_scifact=self.config.exclude_scifact)
        self.structured = StructuredSearchAdapter(db_path=db_path)
        self.llm_client = llm_client or OllamaClient()
        self.semantic_layer = None
        if self.config.semantic_layer:
            from integration.rag.semantic_layer import SemanticLayer
            self.semantic_layer = SemanticLayer(max_chunks_per_doc=self.config.semantic_max_chunks_per_doc)

    def run_query(self, question: str, top_n_context: int = DEFAULT_TOP_N) -> dict:
        structured_results = self.structured.search(question)
        unstructured_results = self.unstructured.search(question, semantic=self.semantic_layer)

        fused = reciprocal_rank_fusion(structured_results, unstructured_results)
        context = build_context(fused, top_n=top_n_context, per_source_budget=self.config.per_source_budget)
        generation = generate_answer(question, context["context_text"], client=self.llm_client)

        return {
            "question": question,
            "structured_results": structured_results,
            "unstructured_results": unstructured_results,
            "fused_results": fused,
            "evidence": context["evidence"],
            "context_text": context["context_text"],
            "answer": generation["answer"],
            "rag_config": self.config.as_dict(),
            "structured_status": self.structured.last_status,
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
