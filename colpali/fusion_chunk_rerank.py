from pathlib import Path
import json
from collections import defaultdict

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder

from retriever import ColPaliRetriever
from fusion import reciprocal_rank_fusion


# ============================================================
# PATHS
# ============================================================

FAISS_INDEX_PATH = Path(
    "data/experiments/public_pdfs/vectorstore/faiss.index"
)

CHUNK_METADATA_PATH = Path(
    "data/experiments/public_pdfs/vectorstore/chunk_metadata_enriched.json"
)

QUERY_PATH = Path(
    "data/experiments/public_pdfs/public_pdf_queries.json"
)

OUTPUT_PATH = Path(
    "data/experiments/public_pdfs/colpali/fusion_chunk_rerank_evaluation.json"
)


# ============================================================
# CONFIGURATION
# ============================================================

FAISS_TOP_K = 20
METADATA_TOP_K = 20
COLPALI_TOP_K = 20

FAISS_SEARCH_K = 200
METADATA_SEARCH_K = 200

RRF_K = 60

CANDIDATE_CHUNKS = 30
FINAL_TOP_K = 10

METADATA_BOOST = 0.15

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ============================================================
# METADATA CONCEPTS
# ============================================================

QUERY_CONCEPTS = {
    "consumer": [
        "consumer_rights",
        "customer_protection",
        "consumer_welfare",
    ],
    "rights": [
        "consumer_rights",
        "customer_protection",
    ],
    "protection": [
        "customer_protection",
        "consumer_welfare",
    ],
    "complaint": [
        "complaint_redressal",
    ],
    "complaints": [
        "complaint_redressal",
    ],
    "grievance": [
        "complaint_redressal",
    ],
    "resolve": [
        "complaint_redressal",
    ],
    "spam": [
        "commercial_communications",
        "spam_control",
    ],
    "unwanted": [
        "commercial_communications",
        "spam_control",
    ],
    "promotional": [
        "commercial_communications",
        "customer_preference",
    ],
    "messages": [
        "commercial_communications",
    ],
    "calls": [
        "commercial_communications",
    ],
    "commercial": [
        "commercial_communications",
    ],
    "telemarketing": [
        "commercial_communications",
    ],
    "quality": [
        "quality_of_service",
    ],
    "service": [
        "quality_of_service",
        "telecom_services",
    ],
    "network": [
        "quality_of_service",
        "network_performance",
    ],
    "call": [
        "quality_of_service",
    ],
    "portability": [
        "mobile_number_portability",
    ],
    "port": [
        "mobile_number_portability",
    ],
    "switch": [
        "mobile_number_portability",
    ],
    "operator": [
        "mobile_number_portability",
    ],
    "number": [
        "mobile_number_portability",
    ],
    "statistics": [
        "telecom_statistics",
        "performance",
    ],
    "performance": [
        "performance",
        "telecom_statistics",
    ],
    "annual": [
        "performance",
        "annual_report",
    ],
    "yearly": [
        "performance",
        "annual_report",
    ],
    "quarterly": [
        "performance",
        "quarterly_report",
    ],
    "proposed": [
        "proposed_regulation",
    ],
    "proposal": [
        "proposed_regulation",
    ],
    "policy": [
        "regulation",
    ],
    "regulation": [
        "regulation",
    ],
    "regulations": [
        "regulation",
    ],
    "report": [
        "reporting",
    ],
    "reporting": [
        "reporting",
    ],
    "submit": [
        "reporting",
    ],
    "submission": [
        "reporting",
    ],
}


# ============================================================
# HELPERS
# ============================================================

def detect_query_tags(query):
    """
    Detect semantic metadata tags from query words.
    """
    query_words = query.lower().replace("?", "").split()

    tags = set()

    for word in query_words:
        if word in QUERY_CONCEPTS:
            tags.update(QUERY_CONCEPTS[word])

    return tags


def normalize_colpali_document_id(document_id):
    """
    Convert ColPali's lowercase/no-prefix document ID into
    the canonical PUBLIC_PDF_... format.
    """
    return "PUBLIC_PDF_" + document_id.upper()


def evaluate(ranked_documents, queries):
    """
    Compute Recall@1/3/5/10 and MRR@10.
    """

    k_values = [1, 3, 5, 10]

    recalls = {
        k: 0
        for k in k_values
    }

    reciprocal_ranks = []

    query_results = []

    for query_record, ranked_docs in zip(queries, ranked_documents):

        relevant = set(query_record["relevant_documents"])

        rank_found = None

        for rank, document_id in enumerate(
            ranked_docs[:10],
            start=1
        ):
            if document_id in relevant:
                rank_found = rank
                break

        for k in k_values:
            if any(
                doc in relevant
                for doc in ranked_docs[:k]
            ):
                recalls[k] += 1

        rr = 0.0 if rank_found is None else 1.0 / rank_found

        reciprocal_ranks.append(rr)

        query_results.append({
            "query_id": query_record["query_id"],
            "query": query_record["query"],
            "relevant_documents": list(relevant),
            "ranked_documents": ranked_docs[:10],
            "first_relevant_rank": rank_found,
            "reciprocal_rank": rr,
        })

    n = len(queries)

    return {
        "Recall@1": recalls[1] / n,
        "Recall@3": recalls[3] / n,
        "Recall@5": recalls[5] / n,
        "Recall@10": recalls[10] / n,
        "MRR@10": sum(reciprocal_ranks) / n,
        "query_results": query_results,
    }


# ============================================================
# LOAD DATA
# ============================================================

print("=" * 80)
print("NOVATEL CHUNK-LEVEL FAISS + METADATA + COLPALI FUSION")
print("=" * 80)


print("\nLoading FAISS index...")

index = faiss.read_index(
    str(FAISS_INDEX_PATH)
)

print(f"FAISS vectors: {index.ntotal}")


print("\nLoading chunk metadata...")

with open(
    CHUNK_METADATA_PATH,
    "r",
    encoding="utf-8"
) as f:
    chunks = json.load(f)

print(f"Chunk records: {len(chunks)}")


print("\nLoading evaluation queries...")

with open(
    QUERY_PATH,
    "r",
    encoding="utf-8"
) as f:
    queries = json.load(f)

print(f"Evaluation queries: {len(queries)}")


# ============================================================
# LOAD MODELS
# ============================================================

print("\nLoading MiniLM...")

minilm = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)


print("\nLoading CrossEncoder...")

cross_encoder = CrossEncoder(
    CROSS_ENCODER_MODEL
)


print("\nLoading ColPali...")

colpali = ColPaliRetriever()


# ============================================================
# MAIN EVALUATION
# ============================================================

all_ranked_documents = []


for query_number, query_record in enumerate(
    queries,
    start=1
):

    query = query_record["query"]

    print(
        f"\n[{query_number}/{len(queries)}] {query}"
    )


    # --------------------------------------------------------
    # 1. FAISS CHUNK RETRIEVAL
    # --------------------------------------------------------

    query_embedding = minilm.encode(
        [query],
        convert_to_numpy=True
    ).astype("float32")

    faiss_scores, faiss_indices = index.search(
        query_embedding,
        FAISS_SEARCH_K
    )

    faiss_ranked_chunks = []

    for idx in faiss_indices[0]:

        if idx < 0:
            continue

        chunk = chunks[idx]

        faiss_ranked_chunks.append(
            chunk["chunk_id"]
        )

        if len(faiss_ranked_chunks) >= FAISS_TOP_K:
            break


    # --------------------------------------------------------
    # 2. METADATA-AWARE CHUNK RETRIEVAL
    # --------------------------------------------------------

    query_tags = detect_query_tags(query)

    metadata_candidates = []

    for score, idx in zip(
        faiss_scores[0],
        faiss_indices[0]
    ):

        if idx < 0:
            continue

        chunk = chunks[idx]

        boosted_score = float(score)

        chunk_tags = set(
            chunk.get("domain_tags", [])
        )

        matching_tags = (
            query_tags & chunk_tags
        )

        boosted_score += (
            METADATA_BOOST *
            len(matching_tags)
        )

        metadata_candidates.append(
            (
                boosted_score,
                chunk["chunk_id"]
            )
        )


    metadata_candidates.sort(
        key=lambda x: x[0],
        reverse=True
    )

    metadata_ranked_chunks = [
        chunk_id
        for _, chunk_id
        in metadata_candidates[:METADATA_TOP_K]
    ]


    # --------------------------------------------------------
    # 3. COLPALI PAGE RETRIEVAL
    # --------------------------------------------------------

    colpali_results = colpali.search(
        query,
        top_k=COLPALI_TOP_K
    )


    # Convert page results into document ranking.

    colpali_doc_scores = {}

    for result in colpali_results:

        document_id = normalize_colpali_document_id(
            result["document_id"]
        )

        score = result["score"]

        if (
            document_id not in colpali_doc_scores
            or score > colpali_doc_scores[document_id]
        ):
            colpali_doc_scores[document_id] = score


    colpali_ranked_documents = [
        document_id
        for document_id, _ in sorted(
            colpali_doc_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
    ]


    # --------------------------------------------------------
    # 4. DOCUMENT CANDIDATES FROM COLPALI
    # --------------------------------------------------------

    colpali_documents = set(
        colpali_ranked_documents
    )


    # --------------------------------------------------------
    # 5. RRF FUSION OF CHUNK RETRIEVERS
    # --------------------------------------------------------

    # FAISS and metadata operate at chunk level.
    # ColPali operates at document/page level.
    #
    # Therefore ColPali is used as a document-level
    # candidate signal rather than pretending its page ID
    # is a chunk ID.

    chunk_lists = [
        faiss_ranked_chunks,
        metadata_ranked_chunks
    ]

    fused_chunks = reciprocal_rank_fusion(
        chunk_lists,
        k=RRF_K
    )


    # --------------------------------------------------------
    # 6. APPLY COLPALI DOCUMENT SIGNAL
    # --------------------------------------------------------

    fused_chunk_scores = []

    for chunk_id, rrf_score in fused_chunks:

        chunk = next(
            c for c in chunks
            if c["chunk_id"] == chunk_id
        )

        document_id = chunk["document_id"]

        score = rrf_score

        # Give a modest bonus to chunks belonging
        # to documents that ColPali independently
        # identified as relevant.

        if document_id in colpali_documents:

            colpali_rank = (
                colpali_ranked_documents.index(
                    document_id
                ) + 1
            )

            score += (
                0.05 /
                (1 + colpali_rank)
            )

        fused_chunk_scores.append(
            (
                score,
                chunk_id
            )
        )


    fused_chunk_scores.sort(
        key=lambda x: x[0],
        reverse=True
    )


    candidate_chunk_ids = [
        chunk_id
        for _, chunk_id
        in fused_chunk_scores[
            :CANDIDATE_CHUNKS
        ]
    ]


    # --------------------------------------------------------
    # 7. CROSSENCODER RERANKING
    # --------------------------------------------------------

    candidate_chunks = []

    for chunk_id in candidate_chunk_ids:

        chunk = next(
            c for c in chunks
            if c["chunk_id"] == chunk_id
        )

        candidate_chunks.append(
            chunk
        )


    pairs = [
        (
            query,
            chunk["text"]
        )
        for chunk in candidate_chunks
    ]


    if pairs:

        ce_scores = cross_encoder.predict(
            pairs
        )

    else:

        ce_scores = []


    reranked = sorted(
        zip(
            ce_scores,
            candidate_chunks
        ),
        key=lambda x: x[0],
        reverse=True
    )


    # --------------------------------------------------------
    # 8. CONVERT CHUNKS → DOCUMENT RANKING
    # --------------------------------------------------------

    document_scores = {}

    for ce_score, chunk in reranked:

        document_id = chunk["document_id"]

        if (
            document_id not in document_scores
            or ce_score > document_scores[document_id]
        ):
            document_scores[document_id] = float(
                ce_score
            )


    ranked_documents = [
        document_id
        for document_id, _
        in sorted(
            document_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
    ]


    all_ranked_documents.append(
        ranked_documents[:FINAL_TOP_K]
    )


    top1 = (
        ranked_documents[0]
        if ranked_documents
        else "NONE"
    )

    print(
        f"Final Top-1: {top1}"
    )


# ============================================================
# EVALUATION
# ============================================================

results = evaluate(
    all_ranked_documents,
    queries
)


print("\n")
print("=" * 80)
print("CHUNK-LEVEL FUSION RESULTS")
print("=" * 80)

print(
    f"Recall@1:  {results['Recall@1']:.4f}"
)

print(
    f"Recall@3:  {results['Recall@3']:.4f}"
)

print(
    f"Recall@5:  {results['Recall@5']:.4f}"
)

print(
    f"Recall@10: {results['Recall@10']:.4f}"
)

print(
    f"MRR@10:    {results['MRR@10']:.4f}"
)


# ============================================================
# SAVE
# ============================================================

OUTPUT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

with open(
    OUTPUT_PATH,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        results,
        f,
        indent=2,
        ensure_ascii=False
    )


print(
    f"\nResults saved to:\n{OUTPUT_PATH}"
)