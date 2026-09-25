import json
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# CONFIGURATION
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
    VECTORSTORE_DIR / "chunk_metadata.json"
)

QUERIES_PATH = (
    EXPERIMENT_DIR / "public_pdf_queries.json"
)

RESULT_PATH = (
    EXPERIMENT_DIR / "public_pdf_retrieval_evaluation.json"
)


MODEL_NAME = (
    "sentence-transformers/all-MiniLM-L6-v2"
)

K_VALUES = [1, 3, 5, 10]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


def get_unique_documents(
    indices,
    metadata,
    max_documents
):
    """
    Convert retrieved chunk indices into unique
    document IDs while preserving ranking order.
    """

    documents = []

    seen = set()

    for index in indices:

        if index < 0:
            continue

        document_id = metadata[index][
            "document_id"
        ]

        if document_id not in seen:

            documents.append(
                document_id
            )

            seen.add(
                document_id
            )

        if len(documents) >= max_documents:

            break

    return documents


def reciprocal_rank(
    retrieved_documents,
    relevant_documents,
    k=10
):
    """
    Calculate reciprocal rank.
    """

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


def recall_at_k(
    retrieved_documents,
    relevant_documents,
    k
):
    """
    For this benchmark, each query currently has
    one relevant document.

    Recall@K = 1 if the relevant document appears
    in the top K retrieved documents.
    """

    relevant_set = set(
        relevant_documents
    )

    retrieved_set = set(
        retrieved_documents[:k]
    )

    relevant_found = len(
        relevant_set.intersection(
            retrieved_set
        )
    )

    return (
        relevant_found /
        len(relevant_set)
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NOVATEL PUBLIC PDF RETRIEVAL EVALUATION")
    print("=" * 70)


    # --------------------------------------------------------
    # CHECK FILES
    # --------------------------------------------------------

    required_files = [
        INDEX_PATH,
        METADATA_PATH,
        QUERIES_PATH
    ]

    for path in required_files:

        if not path.exists():

            print(
                f"\nERROR: Missing file: {path}"
            )

            return


    # --------------------------------------------------------
    # LOAD FAISS INDEX
    # --------------------------------------------------------

    print(
        "\nLoading FAISS index..."
    )

    index = faiss.read_index(
        str(INDEX_PATH)
    )

    print(
        f"Vectors in index: "
        f"{index.ntotal}"
    )


    # --------------------------------------------------------
    # LOAD METADATA
    # --------------------------------------------------------

    print(
        "\nLoading metadata..."
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
        f"Evaluation queries: "
        f"{len(queries)}"
    )


    # --------------------------------------------------------
    # LOAD EMBEDDING MODEL
    # --------------------------------------------------------

    print(
        f"\nLoading embedding model: "
        f"{MODEL_NAME}"
    )

    model = SentenceTransformer(
        MODEL_NAME
    )


    # --------------------------------------------------------
    # EVALUATION STORAGE
    # --------------------------------------------------------

    metrics = {
        f"Recall@{k}": []
        for k in K_VALUES
    }

    mrr_scores = []

    query_results = []


    # --------------------------------------------------------
    # EVALUATE QUERIES
    # --------------------------------------------------------

    print(
        "\nEvaluating queries..."
    )

    for query_number, item in enumerate(
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
        # EMBED QUERY
        # ----------------------------------------------------

        query_embedding = model.encode(
            [query_text],
            normalize_embeddings=True
        ).astype(
            np.float32
        )


        # ----------------------------------------------------
        # RETRIEVE EXTRA CHUNKS
        #
        # We retrieve many chunks because several top chunks
        # may belong to the same document.
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
        # CONVERT TO UNIQUE DOCUMENT RANKING
        # ----------------------------------------------------

        retrieved_documents = (
            get_unique_documents(
                indices[0],
                metadata,
                max_documents=10
            )
        )


        # ----------------------------------------------------
        # CALCULATE METRICS
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
        # STORE QUERY RESULT
        # ----------------------------------------------------

        query_results.append({

            "query_id": item[
                "query_id"
            ],

            "query": query_text,

            "relevant_documents":
                relevant_documents,

            "retrieved_documents":
                retrieved_documents,

            "metrics":
                query_metrics
        })


        print(
            f"Processed "
            f"{query_number}/{len(queries)}"
        )


    # ========================================================
    # AGGREGATE RESULTS
    # ========================================================

    final_metrics = {}

    for k in K_VALUES:

        metric_name = (
            f"Recall@{k}"
        )

        final_metrics[
            metric_name
        ] = float(
            np.mean(
                metrics[
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


    # ========================================================
    # SAVE RESULTS
    # ========================================================

    results = {

        "dataset": (
            "Real-World Public Telecom PDFs"
        ),

        "evaluation_type": (
            "Document-level retrieval evaluation"
        ),

        "embedding_model": MODEL_NAME,

        "index_type": (
            type(index).__name__
        ),

        "total_documents": 10,

        "total_chunks": int(
            index.ntotal
        ),

        "evaluation_queries": len(
            queries
        ),

        "metrics": final_metrics,

        "query_results": query_results
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
        "PUBLIC PDF RETRIEVAL RESULTS"
    )
    print("=" * 70)

    print(
        f"Evaluation queries: "
        f"{len(queries)}"
    )

    print(
        f"Documents in corpus: "
        f"{results['total_documents']}"
    )

    print(
        f"Chunks in index: "
        f"{results['total_chunks']}"
    )

    print()

    for k in K_VALUES:

        metric_name = (
            f"Recall@{k}"
        )

        print(
            f"{metric_name}: "
            f"{final_metrics[metric_name]:.4f}"
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