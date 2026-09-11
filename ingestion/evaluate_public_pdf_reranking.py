
import json
import re
from pathlib import Path

import faiss
import numpy as np

from sentence_transformers import (
    SentenceTransformer,
    CrossEncoder
)


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
    "public_pdf_reranking_evaluation.json"
)


# ============================================================
# MODELS
# ============================================================

EMBEDDING_MODEL_NAME = (
    "sentence-transformers/all-MiniLM-L6-v2"
)

RERANKER_MODEL_NAME = (
    "cross-encoder/ms-marco-MiniLM-L-6-v2"
)


# ============================================================
# SETTINGS
# ============================================================

K_VALUES = [1, 3, 5, 10]

FAISS_SEARCH_K = 200

METADATA_BOOST = 0.15


# ============================================================
# HYBRID WEIGHTS
#
# Format:
#
# (retrieval_weight, reranker_weight)
# ============================================================

HYBRID_WEIGHTS = [

    (0.9, 0.1),

    (0.8, 0.2),

    (0.7, 0.3),

]


# ============================================================
# QUERY → METADATA TAG MAPPING
# ============================================================

QUERY_CONCEPTS = {

    # Consumer protection

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


    # Complaints

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

    "resolving": [
        "complaint_resolution",
        "dispute_resolution"
    ],


    # Spam / commercial communication

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


    # Quality of service

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


    # Mobile number portability

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


    # Statistics / performance

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


    # Regulations / policy

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


    # Reporting

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
# LOAD JSON
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


# ============================================================
# QUERY TAG DETECTION
# ============================================================

def detect_query_tags(query):

    words = set(
        re.findall(
            r"\b\w+\b",
            query.lower()
        )
    )

    detected_tags = set()

    for keyword, tags in QUERY_CONCEPTS.items():

        if keyword in words:

            detected_tags.update(tags)

    return detected_tags


# ============================================================
# METADATA SCORE
# ============================================================

def metadata_score(
    record,
    query_tags
):

    domain_tags = set(
        record.get(
            "domain_tags",
            []
        )
    )

    matches = len(
        query_tags.intersection(
            domain_tags
        )
    )

    return (
        METADATA_BOOST *
        matches
    )


# ============================================================
# MIN-MAX NORMALIZATION
# ============================================================

def min_max_normalize(values):

    values = np.array(
        values,
        dtype=np.float32
    )

    minimum = np.min(values)

    maximum = np.max(values)

    if maximum == minimum:

        return np.ones_like(values)

    return (

        (values - minimum)

        /

        (maximum - minimum)

    )


# ============================================================
# RECALL@K
# ============================================================

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

    if not relevant_set:

        return 0.0

    return (

        len(
            relevant_set.intersection(
                retrieved_set
            )
        )

        /

        len(relevant_set)

    )


# ============================================================
# RECIPROCAL RANK
# ============================================================

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
# GROUP BEST CHUNK PER DOCUMENT
# ============================================================

def group_best_chunks_by_document(
    candidates
):

    best_chunks = {}

    for candidate in candidates:

        document_id = (
            candidate["document_id"]
        )

        if (
            document_id not in best_chunks
        ):

            best_chunks[
                document_id
            ] = candidate

        else:

            if (
                candidate["combined_score"]
                >
                best_chunks[
                    document_id
                ]["combined_score"]
            ):

                best_chunks[
                    document_id
                ] = candidate


    result = list(
        best_chunks.values()
    )


    result.sort(

        key=lambda x:
            x["combined_score"],

        reverse=True

    )


    return result


# ============================================================
# CALCULATE METRICS
# ============================================================

def calculate_metrics(
    query_rankings
):

    results = {

        f"Recall@{k}": []

        for k in K_VALUES

    }


    mrr_scores = []


    for ranking in query_rankings:


        retrieved_documents = (
            ranking[
                "retrieved_documents"
            ]
        )

        relevant_documents = (
            ranking[
                "relevant_documents"
            ]
        )


        for k in K_VALUES:


            results[
                f"Recall@{k}"
            ].append(

                recall_at_k(

                    retrieved_documents,

                    relevant_documents,

                    k

                )

            )


        mrr_scores.append(

            reciprocal_rank(

                retrieved_documents,

                relevant_documents,

                10

            )

        )


    final_metrics = {}


    for k in K_VALUES:


        metric_name = (
            f"Recall@{k}"
        )


        final_metrics[
            metric_name
        ] = float(

            np.mean(
                results[
                    metric_name
                ]
            )

        )


    final_metrics[
        "MRR@10"
    ] = float(
        np.mean(
            mrr_scores
        )
    )


    return final_metrics


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)

    print(
        "NOVATEL PUBLIC PDF HYBRID "
        "METADATA + RERANKING EVALUATION"
    )

    print("=" * 70)


    # --------------------------------------------------------
    # LOAD FILES
    # --------------------------------------------------------

    print(
        "\nLoading FAISS index..."
    )

    index = faiss.read_index(
        str(INDEX_PATH)
    )


    print(
        "Loading metadata..."
    )

    metadata = load_json(
        METADATA_PATH
    )


    print(
        "Loading queries..."
    )

    queries = load_json(
        QUERIES_PATH
    )


    # --------------------------------------------------------
    # LOAD MODELS
    # --------------------------------------------------------

    print(
        "Loading embedding model..."
    )

    embedding_model = (
        SentenceTransformer(
            EMBEDDING_MODEL_NAME
        )
    )


    print(
        "Loading reranker..."
    )

    reranker = CrossEncoder(
        RERANKER_MODEL_NAME
    )


    # ========================================================
    # STORE BASE CANDIDATES
    #
    # We do retrieval only once.
    # Then test multiple hybrid weights.
    # ========================================================

    prepared_queries = []


    print(
        "\nPreparing candidates..."
    )


    for number, item in enumerate(
        queries,
        start=1
    ):


        query_text = (
            item["query"]
        )


        relevant_documents = (
            item[
                "relevant_documents"
            ]
        )


        # ----------------------------------------------------
        # DETECT TAGS
        # ----------------------------------------------------

        query_tags = (
            detect_query_tags(
                query_text
            )
        )


        # ----------------------------------------------------
        # EMBED QUERY
        # ----------------------------------------------------

        query_embedding = (

            embedding_model.encode(

                [query_text],

                normalize_embeddings=True

            )

            .astype(
                np.float32
            )

        )


        # ----------------------------------------------------
        # FAISS SEARCH
        # ----------------------------------------------------

        search_k = min(

            FAISS_SEARCH_K,

            index.ntotal

        )


        scores, indices = (

            index.search(

                query_embedding,

                search_k

            )

        )


        # ----------------------------------------------------
        # CREATE CANDIDATES
        # ----------------------------------------------------

        candidates = []


        for idx, faiss_score in zip(

            indices[0],

            scores[0]

        ):


            if idx < 0:

                continue


            record = metadata[idx]


            boost = (

                metadata_score(

                    record,

                    query_tags

                )

            )


            combined_score = (

                float(faiss_score)

                +

                boost

            )


            candidates.append({

                "document_id":
                    record["document_id"],

                "chunk_id":
                    record.get(
                        "chunk_id",
                        ""
                    ),

                "text":
                    record["text"],

                "faiss_score":
                    float(
                        faiss_score
                    ),

                "metadata_boost":
                    float(
                        boost
                    ),

                "combined_score":
                    float(
                        combined_score
                    )

            })


        # ----------------------------------------------------
        # BEST CHUNK PER DOCUMENT
        # ----------------------------------------------------

        document_candidates = (

            group_best_chunks_by_document(
                candidates
            )

        )


        # ----------------------------------------------------
        # CROSS ENCODER
        # ----------------------------------------------------

        pairs = [

            (

                query_text,

                candidate["text"]

            )

            for candidate
            in document_candidates

        ]


        rerank_scores = (

            reranker.predict(
                pairs
            )

        )


        for candidate, score in zip(

            document_candidates,

            rerank_scores

        ):


            candidate[
                "rerank_score"
            ] = float(
                score
            )


        # ----------------------------------------------------
        # NORMALIZE RETRIEVAL SCORES
        # ----------------------------------------------------

        retrieval_scores = [

            candidate[
                "combined_score"
            ]

            for candidate
            in document_candidates

        ]


        normalized_retrieval = (

            min_max_normalize(
                retrieval_scores
            )

        )


        # ----------------------------------------------------
        # NORMALIZE RERANK SCORES
        # ----------------------------------------------------

        rerank_values = [

            candidate[
                "rerank_score"
            ]

            for candidate
            in document_candidates

        ]


        normalized_rerank = (

            min_max_normalize(
                rerank_values
            )

        )


        # ----------------------------------------------------
        # STORE NORMALIZED SCORES
        # ----------------------------------------------------

        for candidate, retrieval_score, rerank_score in zip(

            document_candidates,

            normalized_retrieval,

            normalized_rerank

        ):


            candidate[
                "normalized_retrieval_score"
            ] = float(
                retrieval_score
            )


            candidate[
                "normalized_rerank_score"
            ] = float(
                rerank_score
            )


        prepared_queries.append({

            "query_id":
                item["query_id"],

            "query":
                query_text,

            "relevant_documents":
                relevant_documents,

            "query_tags":
                sorted(
                    list(
                        query_tags
                    )
                ),

            "document_candidates":
                document_candidates

        })


        print(

            f"Prepared "

            f"{number}/{len(queries)}"

        )


    # ========================================================
    # TEST HYBRID WEIGHTS
    # ========================================================

    all_experiments = {}


    print(
        "\nTesting hybrid weights..."
    )


    for (

        retrieval_weight,

        reranker_weight

    ) in HYBRID_WEIGHTS:


        experiment_name = (

            f"retrieval_"

            f"{retrieval_weight}"

            f"_reranker_"

            f"{reranker_weight}"

        )


        print(
            f"\nExperiment: "
            f"{experiment_name}"
        )


        query_rankings = []


        for prepared in prepared_queries:


            candidates = []


            for candidate in prepared[
                "document_candidates"
            ]:


                hybrid_score = (

                    retrieval_weight

                    *

                    candidate[
                        "normalized_retrieval_score"
                    ]

                    +

                    reranker_weight

                    *

                    candidate[
                        "normalized_rerank_score"
                    ]

                )


                candidates.append({

                    **candidate,

                    "hybrid_score":
                        float(
                            hybrid_score
                        )

                })


            # ------------------------------------------------
            # FINAL HYBRID SORT
            # ------------------------------------------------

            candidates.sort(

                key=lambda x:
                    x["hybrid_score"],

                reverse=True

            )


            retrieved_documents = [

                candidate[
                    "document_id"
                ]

                for candidate
                in candidates

            ]


            query_rankings.append({

                "query_id":
                    prepared[
                        "query_id"
                    ],

                "query":
                    prepared[
                        "query"
                    ],

                "relevant_documents":
                    prepared[
                        "relevant_documents"
                    ],

                "retrieved_documents":
                    retrieved_documents[:10],

                "top_candidates": [

                    {

                        "document_id":
                            candidate[
                                "document_id"
                            ],

                        "hybrid_score":
                            candidate[
                                "hybrid_score"
                            ],

                        "normalized_retrieval_score":
                            candidate[
                                "normalized_retrieval_score"
                            ],

                        "normalized_rerank_score":
                            candidate[
                                "normalized_rerank_score"
                            ]

                    }

                    for candidate
                    in candidates[:10]

                ]

            })


        # ----------------------------------------------------
        # CALCULATE METRICS
        # ----------------------------------------------------

        metrics = (

            calculate_metrics(
                query_rankings
            )

        )


        all_experiments[
            experiment_name
        ] = {

            "retrieval_weight":
                retrieval_weight,

            "reranker_weight":
                reranker_weight,

            "metrics":
                metrics,

            "query_results":
                query_rankings

        }


        print()

        for metric_name, value in metrics.items():

            print(
                f"{metric_name}: "
                f"{value:.4f}"
            )


    # ========================================================
    # FIND BEST EXPERIMENT
    #
    # Primary metric = MRR@10
    # ========================================================

    best_experiment = max(

        all_experiments,

        key=lambda name:

            all_experiments[
                name
            ]["metrics"]["MRR@10"]

    )


    # ========================================================
    # SAVE RESULTS
    # ========================================================

    results = {

        "dataset":
            "Real-World Public Telecom PDFs",

        "evaluation_type":
            "Hybrid metadata-aware retrieval and cross-encoder reranking",

        "embedding_model":
            EMBEDDING_MODEL_NAME,

        "reranker_model":
            RERANKER_MODEL_NAME,

        "faiss_search_k":
            FAISS_SEARCH_K,

        "metadata_boost":
            METADATA_BOOST,

        "hybrid_weights_tested":
            HYBRID_WEIGHTS,

        "best_experiment":
            best_experiment,

        "experiments":
            all_experiments

    }


    with open(

        RESULT_PATH,

        "w",

        encoding="utf-8"

    ) as file:


        json.dump(

            results,

            file,

            indent=4,

            ensure_ascii=False

        )


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print(
        "\n" + "=" * 70
    )

    print(
        "HYBRID RERANKING FINAL SUMMARY"
    )

    print(
        "=" * 70
    )


    for experiment_name, experiment in (
        all_experiments.items()
    ):


        print(
            f"\n{experiment_name}"
        )


        for metric_name, value in (

            experiment[
                "metrics"
            ].items()

        ):


            print(
                f"{metric_name}: "
                f"{value:.4f}"
            )


    print(
        "\nBest experiment:"
    )

    print(
        best_experiment
    )


    print(
        "\nResults saved to:"
    )

    print(
        RESULT_PATH
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()