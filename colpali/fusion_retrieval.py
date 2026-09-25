import json
import re
from pathlib import Path
from collections import defaultdict

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer, CrossEncoder

from retriever import ColPaliRetriever
from fusion import reciprocal_rank_fusion


# ============================================================
# PATHS
# ============================================================

EXPERIMENT_DIR = Path("data/experiments/public_pdfs")

VECTORSTORE_DIR = EXPERIMENT_DIR / "vectorstore"

FAISS_INDEX_PATH = VECTORSTORE_DIR / "faiss.index"
FAISS_METADATA_PATH = VECTORSTORE_DIR / "chunk_metadata.json"
METADATA_ENRICHED_PATH = VECTORSTORE_DIR / "chunk_metadata_enriched.json"

QUERIES_PATH = EXPERIMENT_DIR / "public_pdf_queries.json"

DOCUMENT_DIR = Path("data/processed/documents/public_pdfs")

OUTPUT_PATH = (
    EXPERIMENT_DIR
    / "colpali"
    / "fusion_retrieval_evaluation.json"
)


# ============================================================
# MODELS
# ============================================================

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ============================================================
# RETRIEVAL CONFIGURATION
# ============================================================

FAISS_TOP_K = 20
METADATA_TOP_K = 20
COLPALI_TOP_K = 20

RRF_K = 60

FINAL_TOP_K = 10


# ============================================================
# HELPERS
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_document_id(document_id):
    """
    Convert ColPali document IDs into the benchmark/public-PDF
    document ID format.
    """

    document_id = str(document_id)

    if document_id.startswith("PUBLIC_PDF_"):
        return document_id

    return "PUBLIC_PDF_" + document_id.upper()


def normalize_text(text):
    """
    Basic whitespace normalization for CrossEncoder input.
    """

    if not text:
        return ""

    return re.sub(r"\s+", " ", text).strip()


def load_document_texts():
    """
    Load canonical public-PDF documents.

    Each document contains its full text under the
    'content' field.
    """

    documents = {}

    for path in DOCUMENT_DIR.glob("*.json"):

        data = load_json(path)

        document_id = data["document_id"]

        documents[document_id] = {
            "text": normalize_text(data.get("content", "")),
            "title": data.get("title", ""),
            "category": data.get("category", ""),
            "department": data.get("department", ""),
            "customer_scope": data.get("customer_scope", ""),
            "tags": data.get("tags", []),
        }

    print(f"Loaded canonical documents: {len(documents)}")

    return documents


def get_faiss_document_ranking(
    query,
    model,
    index,
    metadata,
    top_k=20
):
    """
    Retrieve FAISS chunks and convert them into a
    unique document ranking.
    """

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True
    ).astype(np.float32)

    search_k = min(
        200,
        index.ntotal
    )

    scores, indices = index.search(
        query_embedding,
        search_k
    )

    document_scores = {}

    for score, index_id in zip(
        scores[0],
        indices[0]
    ):

        if index_id < 0:
            continue

        document_id = metadata[index_id]["document_id"]

        if document_id not in document_scores:
            document_scores[document_id] = float(score)

    ranked = sorted(
        document_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return [
        document_id
        for document_id, _ in ranked[:top_k]
    ]


def detect_query_tags(query):
    """
    Detect metadata/domain concepts using the same
    concept mapping as the existing metadata-aware
    experiment.
    """

    query_concepts = {

        "consumer": [
            "consumer_rights",
            "customer_protection",
            "consumer_welfare"
        ],

        "rights": [
            "consumer_rights"
        ],

        "protection": [
            "customer_protection",
            "consumer_welfare"
        ],

        "complaint": [
            "customer_complaints",
            "complaint_resolution",
            "grievance"
        ],

        "complaints": [
            "customer_complaints",
            "complaint_resolution",
            "grievance"
        ],

        "grievance": [
            "grievance",
            "dispute_resolution"
        ],

        "resolve": [
            "complaint_resolution",
            "dispute_resolution"
        ],

        "spam": [
            "spam",
            "spam_control"
        ],

        "unwanted": [
            "spam",
            "unsolicited_calls"
        ],

        "promotional": [
            "promotional_messages",
            "promotional_communication"
        ],

        "messages": [
            "promotional_messages",
            "commercial_communication"
        ],

        "calls": [
            "unsolicited_calls",
            "telemarketing"
        ],

        "commercial": [
            "commercial_communication",
            "telemarketing"
        ],

        "telemarketing": [
            "telemarketing"
        ],

        "quality": [
            "service_quality",
            "network_quality",
            "call_quality"
        ],

        "service": [
            "service_quality",
            "telecom_services"
        ],

        "network": [
            "network_quality"
        ],

        "call": [
            "call_quality",
            "unsolicited_calls"
        ],

        "port": [
            "mobile_number_portability",
            "number_portability"
        ],

        "portability": [
            "mobile_number_portability",
            "number_portability"
        ],

        "switch": [
            "switching_operator"
        ],

        "switching": [
            "switching_operator"
        ],

        "operator": [
            "switching_operator"
        ],

        "number": [
            "mobile_number",
            "number_portability"
        ],

        "statistics": [
            "telecom_statistics",
            "subscriber_statistics"
        ],

        "performance": [
            "telecom_performance",
            "industry_performance",
            "annual_performance",
            "quarterly_performance"
        ],

        "annual": [
            "annual_performance"
        ],

        "year": [
            "annual_performance"
        ],

        "yearly": [
            "annual_performance"
        ],

        "quarterly": [
            "quarterly_performance"
        ],

        "subscriber": [
            "subscriber_statistics"
        ],

        "proposed": [
            "proposed_regulations"
        ],

        "proposal": [
            "proposed_regulations"
        ],

        "policy": [
            "telecom_policy"
        ],

        "regulation": [
            "telecom_regulation",
            "proposed_regulations"
        ],

        "regulations": [
            "telecom_regulation",
            "proposed_regulations"
        ],

        "report": [
            "qos_reporting",
            "compliance_reporting",
            "telecom_reporting"
        ],

        "reporting": [
            "qos_reporting",
            "compliance_reporting",
            "telecom_reporting"
        ],

        "submit": [
            "qos_reporting",
            "compliance_reporting"
        ],

        "submission": [
            "qos_reporting",
            "compliance_reporting"
        ]
    }

    words = set(
        re.findall(
            r"\b\w+\b",
            query.lower()
        )
    )

    detected_tags = set()

    for keyword, tags in query_concepts.items():

        if keyword in words:
            detected_tags.update(tags)

    return detected_tags


def get_metadata_document_ranking(
    query,
    metadata,
    model,
    index,
    top_k=20
):
    """
    Reproduce the existing metadata-aware retrieval
    ranking using the enriched metadata.
    """

    query_tags = detect_query_tags(query)

    query_embedding = model.encode(
        [query],
        normalize_embeddings=True
    ).astype(np.float32)

    search_k = min(
        200,
        index.ntotal
    )

    scores, indices = index.search(
        query_embedding,
        search_k
    )

    document_scores = {}

    for score, index_id in zip(
        scores[0],
        indices[0]
    ):

        if index_id < 0:
            continue

        record = metadata[index_id]

        document_id = record["document_id"]

        domain_tags = set(
            record.get("domain_tags", [])
        )

        metadata_matches = len(
            query_tags.intersection(domain_tags)
        )

        boosted_score = (
            float(score)
            + 0.15 * metadata_matches
        )

        if document_id not in document_scores:

            document_scores[document_id] = (
                boosted_score
            )

        else:

            document_scores[document_id] = max(
                document_scores[document_id],
                boosted_score
            )

    ranked = sorted(
        document_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return [
        document_id
        for document_id, _ in ranked[:top_k]
    ]


def get_colpali_document_ranking(
    query,
    colpali_retriever,
    top_k=20
):
    """
    Retrieve ColPali pages and aggregate them into
    document-level ranking using maximum page score.
    """

    page_results = colpali_retriever.search(
        query,
        top_k=878
    )

    document_scores = {}

    for result in page_results:

        raw_document_id = result["document_id"]

        document_id = normalize_document_id(
            raw_document_id
        )

        score = float(
            result["score"]
        )

        if (
            document_id not in document_scores
            or score > document_scores[document_id]
        ):

            document_scores[document_id] = score

    ranked = sorted(
        document_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return [
        document_id
        for document_id, _ in ranked[:top_k]
    ]


def rerank_with_crossencoder(
    query,
    candidate_documents,
    document_texts,
    reranker
):
    """
    Rerank fused document candidates using the
    CrossEncoder.
    """

    valid_candidates = []

    pairs = []

    for document_id in candidate_documents:

        if document_id not in document_texts:
            continue

        text = document_texts[document_id]["text"]

        if not text:
            continue

        valid_candidates.append(
            document_id
        )

        pairs.append(
            (
                query,
                text
            )
        )

    if not pairs:
        return []

    scores = reranker.predict(
        pairs
    )

    ranked = sorted(
        zip(
            valid_candidates,
            scores
        ),
        key=lambda x: float(x[1]),
        reverse=True
    )

    return [
        document_id
        for document_id, _ in ranked
    ]


def recall_at_k(
    retrieved,
    relevant,
    k
):

    return int(
        bool(
            set(retrieved[:k]).intersection(
                set(relevant)
            )
        )
    )


def reciprocal_rank(
    retrieved,
    relevant,
    k=10
):

    relevant = set(relevant)

    for rank, document_id in enumerate(
        retrieved[:k],
        start=1
    ):

        if document_id in relevant:
            return 1.0 / rank

    return 0.0


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("NOVATEL FAISS + METADATA + COLPALI RRF FUSION")
    print("=" * 80)

    # --------------------------------------------------------
    # Check files
    # --------------------------------------------------------

    required_files = [
        FAISS_INDEX_PATH,
        FAISS_METADATA_PATH,
        METADATA_ENRICHED_PATH,
        QUERIES_PATH
    ]

    for path in required_files:

        if not path.exists():

            raise FileNotFoundError(
                f"Missing required file: {path}"
            )

    # --------------------------------------------------------
    # Load FAISS
    # --------------------------------------------------------

    print("\nLoading FAISS index...")

    index = faiss.read_index(
        str(FAISS_INDEX_PATH)
    )

    print(
        f"FAISS vectors: {index.ntotal}"
    )

    # --------------------------------------------------------
    # Load metadata
    # --------------------------------------------------------

    print("\nLoading metadata...")

    faiss_metadata = load_json(
        FAISS_METADATA_PATH
    )

    enriched_metadata = load_json(
        METADATA_ENRICHED_PATH
    )

    print(
        f"FAISS metadata records: "
        f"{len(faiss_metadata)}"
    )

    print(
        f"Enriched metadata records: "
        f"{len(enriched_metadata)}"
    )

    # --------------------------------------------------------
    # Load queries
    # --------------------------------------------------------

    queries = load_json(
        QUERIES_PATH
    )

    print(
        f"Evaluation queries: {len(queries)}"
    )

    # --------------------------------------------------------
    # Load canonical document text
    # --------------------------------------------------------

    print("\nLoading canonical document text...")

    document_texts = load_document_texts()

    # --------------------------------------------------------
    # Load MiniLM
    # --------------------------------------------------------

    print("\nLoading MiniLM...")

    embedding_model = SentenceTransformer(
        EMBEDDING_MODEL_NAME
    )

    # --------------------------------------------------------
    # Load CrossEncoder
    # --------------------------------------------------------

    print("\nLoading CrossEncoder...")

    reranker = CrossEncoder(
        RERANKER_MODEL_NAME
    )

    # --------------------------------------------------------
    # Load ColPali
    # --------------------------------------------------------

    print("\nLoading ColPali...")

    colpali_retriever = ColPaliRetriever()

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    metrics = {
        "Recall@1": [],
        "Recall@3": [],
        "Recall@5": [],
        "Recall@10": []
    }

    mrr_scores = []

    query_results = []

    # ========================================================
    # EVALUATION
    # ========================================================

    for number, item in enumerate(
        queries,
        start=1
    ):

        query = item["query"]

        relevant_documents = [
            normalize_document_id(doc_id)
            for doc_id in item["relevant_documents"]
        ]

        print(
            f"\n[{number}/{len(queries)}] {query}"
        )

        # ----------------------------------------------------
        # 1. FAISS
        # ----------------------------------------------------

        faiss_ranking = get_faiss_document_ranking(
            query,
            embedding_model,
            index,
            faiss_metadata,
            FAISS_TOP_K
        )

        # ----------------------------------------------------
        # 2. Metadata-aware
        # ----------------------------------------------------

        metadata_ranking = get_metadata_document_ranking(
            query,
            enriched_metadata,
            embedding_model,
            index,
            METADATA_TOP_K
        )

        # ----------------------------------------------------
        # 3. ColPali
        # ----------------------------------------------------

        colpali_ranking = get_colpali_document_ranking(
            query,
            colpali_retriever,
            COLPALI_TOP_K
        )

        # ----------------------------------------------------
        # Normalize IDs for all rankings
        # ----------------------------------------------------

        faiss_ranking = [
            normalize_document_id(doc_id)
            for doc_id in faiss_ranking
        ]

        metadata_ranking = [
            normalize_document_id(doc_id)
            for doc_id in metadata_ranking
        ]

        # ----------------------------------------------------
        # 4. RRF fusion
        # ----------------------------------------------------

        fused = reciprocal_rank_fusion(
            [
                faiss_ranking,
                metadata_ranking,
                colpali_ranking
            ],
            k=RRF_K
        )

        fused_ranking = [
            document_id
            for document_id, _ in fused
        ]

        # ----------------------------------------------------
        # 5. CrossEncoder reranking
        # ----------------------------------------------------

        rerank_candidates = (
            fused_ranking[:30]
        )

        final_ranking = rerank_with_crossencoder(
            query,
            rerank_candidates,
            document_texts,
            reranker
        )

        # ----------------------------------------------------
        # Metrics
        # ----------------------------------------------------

        query_metrics = {}

        for k in [1, 3, 5, 10]:

            score = recall_at_k(
                final_ranking,
                relevant_documents,
                k
            )

            metrics[
                f"Recall@{k}"
            ].append(score)

            query_metrics[
                f"Recall@{k}"
            ] = score

        rr = reciprocal_rank(
            final_ranking,
            relevant_documents
        )

        mrr_scores.append(rr)

        query_metrics[
            "MRR@10"
        ] = rr

        # ----------------------------------------------------
        # Save detailed result
        # ----------------------------------------------------

        query_results.append(
            {
                "query_id":
                    item["query_id"],

                "query":
                    query,

                "relevant_documents":
                    relevant_documents,

                "faiss_top20":
                    faiss_ranking,

                "metadata_top20":
                    metadata_ranking,

                "colpali_top20":
                    colpali_ranking,

                "rrf_top30":
                    fused_ranking[:30],

                "final_top10":
                    final_ranking[:10],

                "metrics":
                    query_metrics
            }
        )

        print(
            f"Final Top-1: "
            f"{final_ranking[0] if final_ranking else 'NONE'}"
        )

    # ========================================================
    # AGGREGATE
    # ========================================================

    final_metrics = {}

    for k in [1, 3, 5, 10]:

        name = f"Recall@{k}"

        final_metrics[name] = float(
            np.mean(
                metrics[name]
            )
        )

    final_metrics["MRR@10"] = float(
        np.mean(mrr_scores)
    )

    # ========================================================
    # SAVE
    # ========================================================

    results = {

        "dataset":
            "Real-World Public Telecom PDFs",

        "evaluation_type":
            "FAISS + metadata + ColPali RRF fusion + CrossEncoder",

        "embedding_model":
            EMBEDDING_MODEL_NAME,

        "colpali_model":
            "vidore/colpali-v1.3-hf",

        "reranker_model":
            RERANKER_MODEL_NAME,

        "parameters": {

            "faiss_top_k":
                FAISS_TOP_K,

            "metadata_top_k":
                METADATA_TOP_K,

            "colpali_top_k":
                COLPALI_TOP_K,

            "rrf_k":
                RRF_K,

            "crossencoder_candidates":
                30,

            "final_top_k":
                FINAL_TOP_K
        },

        "evaluation_queries":
            len(queries),

        "metrics":
            final_metrics,

        "query_results":
            query_results
    }

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
            indent=4,
            ensure_ascii=False
        )

    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print("\n" + "=" * 80)
    print("FUSION RESULTS")
    print("=" * 80)

    for k in [1, 3, 5, 10]:

        print(
            f"Recall@{k}: "
            f"{final_metrics[f'Recall@{k}']:.4f}"
        )

    print(
        f"MRR@10: "
        f"{final_metrics['MRR@10']:.4f}"
    )

    print("\nResults saved to:")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()