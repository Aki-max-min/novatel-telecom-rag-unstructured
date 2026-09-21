"""Graph-augmented retrieval: FAISS vector search fused with KG expansion.

Pipeline per query:

1. **Vector**  - Person A's FAISS retrieval, reused as-is. This module imports
   ``ingestion.evaluate_retrieval`` for the index path, metadata path, model name
   and benchmark path, and performs the identical encode -> search sequence
   (their file exposes no callable search function - only ``main()`` and
   ``load_chunk_text`` - so the sequence is mirrored rather than called, using
   their constants, and the reproduced baseline is checked against their stored
   numbers in evaluate_graph_rag.py).
2. **Graph expansion** - the top-M vector documents are used as seeds; the
   knowledge graph returns documents that share a Service, Channel,
   VerificationMethod (the content-layer bridges) or a Tag with a seed.
3. **Fusion** - Reciprocal Rank Fusion. Vector similarities and graph overlap
   counts live on incompatible scales, so nothing is added directly: only ranks
   are combined, ``score(d) = sum over lists of weight / (k + rank(d))``.

Category expansion is deliberately **not** part of the main graph signal. The
benchmark has one question per category, so expanding by category is close to
handing the system the answer label. It is available via
``include_category=True`` and is reported as a separate diagnostic row.

Usage::

    python -m knowledge_graph.graph_augmented_retrieval "how do I update my number"

Requires an environment with sentence-transformers + faiss (the same one Person
A's pipeline runs in).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from knowledge_graph.graph_builder import GRAPH_JSON_PATH

# Content-layer node labels that act as bridges between documents, plus Tag.
BRIDGE_LABELS: Tuple[str, ...] = ("Service", "Channel", "VerificationMethod")
DEFAULT_BRIDGES: Tuple[str, ...] = BRIDGE_LABELS + ("Tag",)
CATEGORY_LABEL = "Category"

MENTION_EDGE_TYPES = {
    "MENTIONS_SERVICE": "Service",
    "MENTIONS_CHANNEL": "Channel",
    "MENTIONS_VERIFICATION": "VerificationMethod",
    "MENTIONS_REQUIREMENT": "Requirement",
    "MENTIONS_LOCATION": "Location",
    "HAS_TAG": "Tag",
    "BELONGS_TO_CATEGORY": "Category",
}

# Retrieval depths. Metrics are reported @1/@3/@5; the deeper vector list only
# feeds fusion.
VECTOR_DEPTH = 10
GRAPH_SEEDS = 5
GRAPH_CANDIDATES = 20
RRF_K = 60


# ---------------------------------------------------------------------------
# Graph side
# ---------------------------------------------------------------------------
@dataclass
class GraphIndex:
    """Document <-> concept adjacency, built once from output/graph.json."""

    document_concepts: Dict[str, Dict[str, set]] = field(default_factory=dict)
    concept_documents: Dict[str, Dict[str, set]] = field(default_factory=dict)
    known_documents: set = field(default_factory=set)

    def concepts_of(self, document_id: str, labels: Sequence[str]) -> set:
        found = set()
        for label in labels:
            found |= self.document_concepts.get(document_id, {}).get(label, set())
        return found

    def documents_of(self, label: str, concept: str) -> set:
        return self.concept_documents.get(label, {}).get(concept, set())


def load_graph_index(path: Path = GRAPH_JSON_PATH) -> GraphIndex:
    """Build the adjacency the expansion needs from the built graph JSON."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the graph first: python -m knowledge_graph.graph_builder"
        )
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    labels_by_node = {node["id"]: node["label"] for node in payload["nodes"]}
    keys_by_node = {node["id"]: node["key"] for node in payload["nodes"]}

    index = GraphIndex()
    index.known_documents = {
        node["key"]
        for node in payload["nodes"]
        if node["label"] == "Document" and node["properties"].get("resolved", True)
    }

    for edge in payload["edges"]:
        label = MENTION_EDGE_TYPES.get(edge["type"])
        if label is None:
            continue
        source_label = labels_by_node.get(edge["source"])
        if source_label != "Document":
            continue
        document_id = keys_by_node[edge["source"]]
        concept = keys_by_node[edge["target"]]
        index.document_concepts.setdefault(document_id, {}).setdefault(label, set()).add(concept)
        index.concept_documents.setdefault(label, {}).setdefault(concept, set()).add(document_id)

    return index


def graph_expand(
    seed_documents: Sequence[str],
    graph_index: GraphIndex,
    bridges: Sequence[str] = DEFAULT_BRIDGES,
    limit: int = GRAPH_CANDIDATES,
) -> List[Dict[str, Any]]:
    """Documents sharing a bridge concept with one of the seed documents.

    Candidates are scored by how strongly they are attached to the seeds:
    each shared concept contributes ``1 / (1 + seed_rank)``, so a concept shared
    with the top vector hit counts for more than one shared with the fifth. The
    score orders the graph list; only its *rank* reaches the fusion step.
    """
    scores: Dict[str, float] = defaultdict(float)
    shared: Dict[str, set] = defaultdict(set)
    seeds = set(seed_documents)

    for seed_rank, seed in enumerate(seed_documents):
        seed_weight = 1.0 / (1 + seed_rank)
        for label in bridges:
            for concept in graph_index.concepts_of(seed, [label]):
                for neighbour in graph_index.documents_of(label, concept):
                    if neighbour == seed:
                        continue
                    scores[neighbour] += seed_weight
                    shared[neighbour].add(f"{label}:{concept}")

    candidates = [
        {
            "document_id": document_id,
            "graph_score": round(score, 6),
            "shared_concepts": sorted(shared[document_id]),
            "shared_count": len(shared[document_id]),
            "is_seed": document_id in seeds,
        }
        for document_id, score in scores.items()
    ]
    candidates.sort(
        key=lambda row: (-row["graph_score"], -row["shared_count"], row["document_id"])
    )
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------
def reciprocal_rank_fusion(
    rankings: Sequence[Tuple[str, Sequence[str], float]],
    k: int = RRF_K,
) -> List[Dict[str, Any]]:
    """Fuse ranked id lists. ``rankings`` is (name, ordered ids, weight).

    RRF is used precisely because FAISS cosine scores and graph overlap counts
    are not comparable: only positions enter the sum.
    """
    scores: Dict[str, float] = defaultdict(float)
    contributions: Dict[str, Dict[str, int]] = defaultdict(dict)

    for name, ordered, weight in rankings:
        for rank, document_id in enumerate(ordered, start=1):
            scores[document_id] += weight / (k + rank)
            contributions[document_id][name] = rank

    fused = [
        {
            "document_id": document_id,
            "rrf_score": round(score, 8),
            "ranks": dict(sorted(contributions[document_id].items())),
        }
        for document_id, score in scores.items()
    ]
    # Ties broken by best single-list rank, then id, so the order is stable.
    fused.sort(
        key=lambda row: (
            -row["rrf_score"],
            min(row["ranks"].values()),
            row["document_id"],
        )
    )
    return fused


# ---------------------------------------------------------------------------
# Vector side (Person A's retrieval, reused)
# ---------------------------------------------------------------------------
class VectorRetriever:
    """Thin wrapper over Person A's FAISS assets.

    Nothing about the embedding or the index is reimplemented: the model name,
    index path and metadata path all come from ``ingestion.evaluate_retrieval``,
    and the encode/search call matches theirs exactly (normalised embeddings,
    ``index.search``).
    """

    def __init__(self) -> None:
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "sentence-transformers and faiss are required for retrieval. "
                "Run this in the environment Person A's pipeline uses "
                "(the one where `python -m ingestion.evaluate_retrieval` works)."
            ) from error

        import ingestion.evaluate_retrieval as person_a

        self.person_a = person_a
        self.model = SentenceTransformer(person_a.MODEL_NAME, local_files_only=True)
        self.index = faiss.read_index(str(person_a.INDEX_PATH))
        with open(person_a.METADATA_PATH, encoding="utf-8") as handle:
            self.metadata = json.load(handle)

    @property
    def size(self) -> int:
        return self.index.ntotal

    def search(self, question: str, depth: int = VECTOR_DEPTH) -> List[Dict[str, Any]]:
        """Ranked chunks for a question, mapped to documents (first hit wins)."""
        embedding = self.model.encode(
            [question], convert_to_numpy=True, normalize_embeddings=True
        ).astype("float32")
        depth = min(depth, self.index.ntotal)
        scores, indices = self.index.search(embedding, depth)

        ranked: List[Dict[str, Any]] = []
        seen: set = set()
        for score, position in zip(scores[0], indices[0]):
            entry = self.metadata[position]
            document_id = entry["document_id"]
            if document_id in seen:
                # Deeper chunks of a document already ranked do not re-enter the
                # document-level list; the document keeps its best rank.
                continue
            seen.add(document_id)
            ranked.append(
                {
                    "document_id": document_id,
                    "chunk_id": entry["chunk_id"],
                    "title": entry.get("title", ""),
                    "category": entry.get("category", ""),
                    "score": float(score),
                }
            )
        return ranked


# ---------------------------------------------------------------------------
# Combined retrieval
# ---------------------------------------------------------------------------
@dataclass
class RetrievalResult:
    question: str
    vector_documents: List[str]
    graph_documents: List[str]
    fused_documents: List[str]
    documents_added_by_graph: List[str]
    graph_candidates: List[Dict[str, Any]]
    fused_detail: List[Dict[str, Any]]
    bridges_used: Tuple[str, ...]

    @property
    def added_count(self) -> int:
        return len(self.documents_added_by_graph)


def graph_enhanced_search(
    question: str,
    retriever: VectorRetriever,
    graph_index: GraphIndex,
    vector_depth: int = VECTOR_DEPTH,
    seeds: int = GRAPH_SEEDS,
    graph_limit: int = GRAPH_CANDIDATES,
    include_category: bool = False,
    vector_weight: float = 1.0,
    graph_weight: float = 1.0,
    rrf_k: int = RRF_K,
) -> RetrievalResult:
    """Vector retrieval fused with graph expansion via RRF."""
    bridges: Tuple[str, ...] = DEFAULT_BRIDGES
    if include_category:
        bridges = bridges + (CATEGORY_LABEL,)

    vector_hits = retriever.search(question, depth=vector_depth)
    vector_documents = [hit["document_id"] for hit in vector_hits]

    candidates = graph_expand(
        vector_documents[:seeds], graph_index, bridges=bridges, limit=graph_limit
    )
    graph_documents = [row["document_id"] for row in candidates]

    fused_detail = reciprocal_rank_fusion(
        [
            ("vector", vector_documents, vector_weight),
            ("graph", graph_documents, graph_weight),
        ],
        k=rrf_k,
    )
    fused_documents = [row["document_id"] for row in fused_detail]

    added = [doc for doc in graph_documents if doc not in set(vector_documents)]

    return RetrievalResult(
        question=question,
        vector_documents=vector_documents,
        graph_documents=graph_documents,
        fused_documents=fused_documents,
        documents_added_by_graph=added,
        graph_candidates=candidates,
        fused_detail=fused_detail,
        bridges_used=bridges,
    )


def _demo(question: str) -> int:
    graph_index = load_graph_index()
    try:
        retriever = VectorRetriever()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 2

    result = graph_enhanced_search(question, retriever, graph_index)
    print(f"question: {question}")
    print(f"vector index: {retriever.size} vectors")
    print(f"bridges: {', '.join(result.bridges_used)}")
    print("\n-- vector-only (top 5) --")
    for rank, document_id in enumerate(result.vector_documents[:5], start=1):
        print(f"  {rank}. {document_id}")
    print("\n-- graph expansion (top 8) --")
    for rank, row in enumerate(result.graph_candidates[:8], start=1):
        marker = "seed" if row["is_seed"] else "new "
        print(
            f"  {rank}. [{marker}] {row['document_id']:<26} "
            f"score={row['graph_score']:.3f} via {', '.join(row['shared_concepts'][:3])}"
        )
    print("\n-- fused RRF (top 5) --")
    for rank, row in enumerate(result.fused_detail[:5], start=1):
        print(f"  {rank}. {row['document_id']:<26} rrf={row['rrf_score']:.5f} ranks={row['ranks']}")
    print(f"\ndocuments added by graph (not in vector top-{VECTOR_DEPTH}): {result.added_count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Graph-augmented retrieval demo.")
    parser.add_argument(
        "question",
        nargs="?",
        default="How do I update the mobile number registered on my account?",
    )
    args = parser.parse_args()
    return _demo(args.question)


if __name__ == "__main__":
    raise SystemExit(main())
