import json
import re
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# PATHS
# ============================================================

EXPERIMENT_DIR = Path(
    "data/experiments/public_pdfs"
)

VECTORSTORE_DIR = (
    EXPERIMENT_DIR / "vectorstore"
)

INDEX_PATH = (
    VECTORSTORE_DIR / "faiss.index"
)

METADATA_PATH = (
    VECTORSTORE_DIR /
    "chunk_metadata_enriched.json"
)

QUERIES_PATH = (
    EXPERIMENT_DIR /
    "public_pdf_queries.json"
)

RESULT_PATH = (
    EXPERIMENT_DIR /
    "public_pdf_metadata_retrieval_evaluation.json"
)


# ============================================================
# MODEL
# ============================================================

MODEL_NAME = (
    "sentence-transformers/all-MiniLM-L6-v2"
)

K_VALUES = [1, 3, 5, 10]


# ============================================================
# METADATA BOOST CONFIGURATION
# ============================================================

METADATA_BOOST = 0.15


# Query concepts mapped to domain metadata tags.

QUERY_CONCEPTS = {

    # --------------------------------------------------------
    # Consumer protection
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Complaints
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Commercial communication / spam
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Quality of service
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Portability
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Statistics / performance
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Regulations / policy
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Reporting
    # --------------------------------------------------------

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


# ============================================================
# HELPERS
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def detect_query_tags(query):

    """
    Detect domain concepts from the user query.
    """

    query = query.lower()

    words = set(
        re.findall(
            r"\b\w+\b",
            query
        )
    )

    detected_tags = set()

    for keyword, tags in QUERY_CONCEPTS.items():

        if keyword in words:

            detected_tags.update(
                tags
            )

    return detected_tags


def get_document_scores(
    indices,
    scores,
    metadata,
    query_tags
):

    """
    Aggregate chunk-level FAISS scores
    into document-level scores.

    Metadata matches receive a small boost.
    """

    document_scores = {}

    for index, similarity_score in zip(
        indices,
        scores
    ):

        if index < 0:

            continue


        record = metadata[index]

        document_id = record[
            "document_id"
        ]


        domain_tags = set(
            record.get(
                "domain_tags",
                []
            )
        )


        metadata_matches = len(
            query_tags.intersection(
                domain_tags
            )
        )


        boosted_score = float(
            similarity_score
        ) + (
            METADATA_BOOST *
            metadata_matches
        )


        # Keep best chunk score per document

        if (
            document_id not in
            document_scores
        ):

            document_scores[
                document_id
            ] = boosted_score

        else:

            document_scores[
                document_id
            ] = max(
                document_scores[
                    document_id
                ],
                boosted_score
            )


    return document_scores


def rank_documents(
    document_scores
):

    """
    Sort documents by final score.
    """

    ranked = sorted(
        document_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return [
        document_id
        for document_id, score in ranked
    ]


def recall_at_k(
    retrieved_documents,
    relevant_documents,
    k
):

    relevant_set = set(
        relevant_documents
    )

    retrieved_set = set(
        retrieved_documents[:k]
    )

    return (
        len(
            relevant_set.intersection(
                retrieved_set
            )
        )
        /
        len(relevant_set)
    )


def reciprocal_rank(
    retrieved_documents,
    relevant_documents,
    k=10
):

    relevant_set = set(
        relevant_documents
    )

    for rank, document_id in enumerate(
        retrieved_documents[:k],
        start=1
    ):

        if document_id in relevant_set:

            return 1.0 / rank

    return 0.0


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "NOVATEL PUBLIC PDF METADATA-AWARE RETRIEVAL"
    )
    print("=" * 70)


    # --------------------------------------------------------
    # FILE CHECK
    # --------------------------------------------------------

    required_files = [
        INDEX_PATH,
        METADATA_PATH,
        QUERIES_PATH
    ]

    for path in required_files:

        if not path.exists():

            print(
                f"\nERROR: Missing file:"
            )

            print(path)

            return


    # --------------------------------------------------------
    # LOAD INDEX
    # --------------------------------------------------------

    print(
        "\nLoading FAISS index..."
    )

    index = faiss.read_index(
        str(INDEX_PATH)
    )

    print(
        f"Vectors: "
        f"{index.ntotal}"
    )


    # --------------------------------------------------------
    # LOAD METADATA
    # --------------------------------------------------------

    print(
        "\nLoading enriched metadata..."
    )

    metadata = load_json(
        METADATA_PATH
    )

    print(
        f"Metadata records: "
        f"{len(metadata)}"
    )


    # --------------------------------------------------------
    # LOAD QUERIES
    # --------------------------------------------------------

    print(
        "\nLoading evaluation queries..."
    )

    queries = load_json(
        QUERIES_PATH
    )

    print(
        f"Queries: "
        f"{len(queries)}"
    )


    # --------------------------------------------------------
    # LOAD MODEL
    # --------------------------------------------------------

    print(
        "\nLoading embedding model..."
    )

    model = SentenceTransformer(
        MODEL_NAME
    )


    # --------------------------------------------------------
    # METRIC STORAGE
    # --------------------------------------------------------

    metrics = {
        f"Recall@{k}": []
        for k in K_VALUES
    }

    mrr_scores = []

    query_results = []


    # --------------------------------------------------------
    # EVALUATION LOOP
    # --------------------------------------------------------

    print(
        "\nEvaluating queries..."
    )


    for number, item in enumerate(
        queries,
        start=1
    ):

        query_text = item[
            "query"
        ]

        relevant_documents = item[
            "relevant_documents"
        ]


        # ----------------------------------------------------
        # DETECT QUERY TAGS
        # ----------------------------------------------------

        query_tags = detect_query_tags(
            query_text
        )


        # ----------------------------------------------------
        # EMBED QUERY
        # ----------------------------------------------------

        query_embedding = model.encode(
            [query_text],
            normalize_embeddings=True
        ).astype(
            np.float32
        )


        # ----------------------------------------------------
        # RETRIEVE CHUNKS
        # ----------------------------------------------------

        search_k = min(
            200,
            index.ntotal
        )

        scores, indices = index.search(
            query_embedding,
            search_k
        )


        # ----------------------------------------------------
        # AGGREGATE + BOOST
        # ----------------------------------------------------

        document_scores = (
            get_document_scores(
                indices[0],
                scores[0],
                metadata,
                query_tags
            )
        )


        retrieved_documents = (
            rank_documents(
                document_scores
            )
        )


        # ----------------------------------------------------
        # METRICS
        # ----------------------------------------------------

        query_metrics = {}

        for k in K_VALUES:

            score = recall_at_k(
                retrieved_documents,
                relevant_documents,
                k
            )

            metrics[
                f"Recall@{k}"
            ].append(
                score
            )

            query_metrics[
                f"Recall@{k}"
            ] = score


        rr = reciprocal_rank(
            retrieved_documents,
            relevant_documents,
            k=10
        )

        mrr_scores.append(
            rr
        )

        query_metrics[
            "ReciprocalRank@10"
        ] = rr


        # ----------------------------------------------------
        # STORE RESULT
        # ----------------------------------------------------

        query_results.append({

            "query_id":
                item["query_id"],

            "query":
                query_text,

            "detected_metadata_tags":
                sorted(
                    list(query_tags)
                ),

            "relevant_documents":
                relevant_documents,

            "retrieved_documents":
                retrieved_documents[:10],

            "metrics":
                query_metrics
        })


        print(
            f"Processed "
            f"{number}/{len(queries)}"
        )


    # ========================================================
    # AGGREGATE METRICS
    # ========================================================

    final_metrics = {}

    for k in K_VALUES:

        name = f"Recall@{k}"

        final_metrics[name] = float(
            np.mean(
                metrics[name]
            )
        )


    final_metrics[
        "MRR@10"
    ] = float(
        np.mean(
            mrr_scores
        )
    )


    # ========================================================
    # SAVE RESULTS
    # ========================================================

    results = {

        "dataset":
            "Real-World Public Telecom PDFs",

        "evaluation_type":
            "Metadata-aware document-level retrieval",

        "embedding_model":
            MODEL_NAME,

        "metadata_boost":
            METADATA_BOOST,

        "total_documents":
            10,

        "total_chunks":
            int(index.ntotal),

        "evaluation_queries":
            len(queries),

        "metrics":
            final_metrics,

        "query_results":
            query_results
    }


    with open(
        RESULT_PATH,
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

    print("\n" + "=" * 70)
    print(
        "METADATA-AWARE RETRIEVAL RESULTS"
    )
    print("=" * 70)

    print(
        f"Evaluation queries: "
        f"{len(queries)}"
    )

    print(
        f"Documents in corpus: 10"
    )

    print(
        f"Chunks in index: "
        f"{index.ntotal}"
    )

    print()

    for k in K_VALUES:

        name = f"Recall@{k}"

        print(
            f"{name}: "
            f"{final_metrics[name]:.4f}"
        )


    print(
        f"MRR@10: "
        f"{final_metrics['MRR@10']:.4f}"
    )


    print(
        "\nResults saved to:"
    )

    print(
        RESULT_PATH
    )


if __name__ == "__main__":
    main()