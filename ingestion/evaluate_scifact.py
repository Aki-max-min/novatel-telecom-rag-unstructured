import os
import json
import csv
import numpy as np
import faiss

from sentence_transformers import SentenceTransformer


# ============================================================
# CONFIGURATION
# ============================================================

VECTORSTORE_DIR = "data/vectorstore"

METADATA_PATH = os.path.join(
    VECTORSTORE_DIR,
    "chunk_metadata.json"
)

FAISS_INDEX_PATH = os.path.join(
    VECTORSTORE_DIR,
    "faiss.index"
)

SCIFACT_QUERIES_PATH = (
    "data/raw/real_world/scifact/scifact/queries.jsonl"
)

SCIFACT_QRELS_PATH = (
    "data/raw/real_world/scifact/scifact/qrels/test.tsv"
)

OUTPUT_PATH = (
    "data/vectorstore/scifact_retrieval_evaluation.json"
)

MODEL_NAME = "all-MiniLM-L6-v2"

TOP_K_VALUES = [1, 3, 5, 10]

# Search more chunks because multiple chunks
# may belong to the same document
SEARCH_K = 100


# ============================================================
# NORMALIZE DOCUMENT ID
# ============================================================

def normalize_document_id(document_id):

    document_id = str(document_id)

    # Convert:
    # SCIFACT_31715818 -> 31715818

    if document_id.startswith("SCIFACT_"):

        document_id = document_id.replace(
            "SCIFACT_",
            "",
            1
        )

    return document_id


# ============================================================
# CHECK WHETHER DOCUMENT IS SCIFACT
# ============================================================

def is_scifact_document(item):

    document_id = str(
        item.get("document_id", "")
    )

    return document_id.startswith(
        "SCIFACT_"
    )


# ============================================================
# LOAD QUERIES
# ============================================================

def load_queries():

    queries = {}

    with open(
        SCIFACT_QUERIES_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        for line in f:

            if not line.strip():
                continue

            data = json.loads(line)

            query_id = str(
                data["_id"]
            )

            query_text = data["text"]

            queries[query_id] = query_text

    return queries


# ============================================================
# LOAD QRELS
# ============================================================

def load_qrels():

    qrels = {}

    with open(
        SCIFACT_QRELS_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        reader = csv.DictReader(
            f,
            delimiter="\t"
        )

        for row in reader:

            query_id = str(
                row["query-id"]
            )

            corpus_id = str(
                row["corpus-id"]
            )

            score = int(
                row["score"]
            )

            # Keep only relevant documents

            if score > 0:

                if query_id not in qrels:

                    qrels[query_id] = set()

                qrels[query_id].add(
                    corpus_id
                )

    return qrels


# ============================================================
# GET INDEXED SCIFACT DOCUMENT IDS
# ============================================================

def get_indexed_scifact_document_ids(
    metadata
):

    indexed_docs = set()

    for item in metadata:

        if not is_scifact_document(item):
            continue

        document_id = normalize_document_id(
            item["document_id"]
        )

        indexed_docs.add(
            document_id
        )

    return indexed_docs


# ============================================================
# FILTER VALID QUERIES
# ============================================================

def filter_valid_queries(
    queries,
    qrels,
    indexed_document_ids
):

    valid_queries = {}

    valid_qrels = {}

    for query_id, relevant_docs in qrels.items():

        # Query must exist

        if query_id not in queries:
            continue

        # Keep only ground-truth documents
        # that actually exist in our index

        available_relevant_docs = (
            relevant_docs.intersection(
                indexed_document_ids
            )
        )

        # Keep query only if at least one
        # relevant document exists in our index

        if len(available_relevant_docs) > 0:

            valid_queries[query_id] = (
                queries[query_id]
            )

            valid_qrels[query_id] = (
                available_relevant_docs
            )

    return (
        valid_queries,
        valid_qrels
    )


# ============================================================
# RETRIEVE SCIFACT DOCUMENTS ONLY
# ============================================================

def retrieve_scifact_documents(
    query_embedding,
    index,
    metadata,
    top_k
):

    # Search all available vectors so we can
    # filter out NovaTel documents afterwards

    search_k = min(
        SEARCH_K,
        index.ntotal
    )

    distances, indices = index.search(
        query_embedding,
        search_k
    )

    retrieved_documents = []

    seen_documents = set()

    for idx in indices[0]:

        if idx == -1:
            continue

        item = metadata[idx]

        # Ignore NovaTel documents

        if not is_scifact_document(item):
            continue

        document_id = normalize_document_id(
            item["document_id"]
        )

        # Avoid duplicate chunks from same document

        if document_id not in seen_documents:

            retrieved_documents.append(
                document_id
            )

            seen_documents.add(
                document_id
            )

        # Stop when enough unique documents found

        if len(retrieved_documents) >= top_k:
            break

    return retrieved_documents


# ============================================================
# RECALL@K
# ============================================================

def calculate_recall_at_k(
    retrieved,
    relevant,
    k
):

    retrieved_k = retrieved[:k]

    relevant_found = len(
        set(retrieved_k).intersection(
            relevant
        )
    )

    return relevant_found / len(relevant)


# ============================================================
# MRR@K
# ============================================================

def calculate_mrr(
    retrieved,
    relevant,
    k
):

    retrieved_k = retrieved[:k]

    for rank, document_id in enumerate(
        retrieved_k,
        start=1
    ):

        if document_id in relevant:

            return 1 / rank

    return 0


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NOVATEL SCIFACT RETRIEVAL EVALUATION")
    print("=" * 70)

    # --------------------------------------------------------
    # LOAD FAISS INDEX
    # --------------------------------------------------------

    print("\nLoading FAISS index...")

    index = faiss.read_index(
        FAISS_INDEX_PATH
    )

    print(
        f"Vectors in index: "
        f"{index.ntotal}"
    )

    # --------------------------------------------------------
    # LOAD METADATA
    # --------------------------------------------------------

    print("\nLoading metadata...")

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)

    print(
        f"Metadata records: "
        f"{len(metadata)}"
    )

    # --------------------------------------------------------
    # IDENTIFY SCIFACT DOCUMENTS
    # --------------------------------------------------------

    indexed_scifact_documents = (
        get_indexed_scifact_document_ids(
            metadata
        )
    )

    print(
        f"SciFact documents in index: "
        f"{len(indexed_scifact_documents)}"
    )

    # --------------------------------------------------------
    # LOAD QUERIES
    # --------------------------------------------------------

    print("\nLoading SciFact queries...")

    queries = load_queries()

    print(
        f"Total SciFact queries: "
        f"{len(queries)}"
    )

    # --------------------------------------------------------
    # LOAD QRELS
    # --------------------------------------------------------

    print(
        "\nLoading SciFact relevance labels..."
    )

    qrels = load_qrels()

    print(
        f"Queries with relevance labels: "
        f"{len(qrels)}"
    )

    # --------------------------------------------------------
    # FILTER VALID QUERIES
    # --------------------------------------------------------

    valid_queries, valid_qrels = (
        filter_valid_queries(
            queries,
            qrels,
            indexed_scifact_documents
        )
    )

    print(
        "\nFiltered evaluation set:"
    )

    print(
        f"Indexed SciFact documents: "
        f"{len(indexed_scifact_documents)}"
    )

    print(
        f"Valid evaluation queries: "
        f"{len(valid_queries)}"
    )

    # --------------------------------------------------------
    # STOP IF NO VALID QUERIES
    # --------------------------------------------------------

    if len(valid_queries) == 0:

        print(
            "\nERROR: No valid evaluation queries found."
        )

        print(
            "This means none of the indexed SciFact "
            "documents overlap with the official test qrels."
        )

        print(
            "\nPossible reason:"
        )

        print(
            "Your 100-document subset may have been selected "
            "without considering which documents are referenced "
            "by SciFact test queries."
        )

        return

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
    # METRIC STORAGE
    # --------------------------------------------------------

    recall_scores = {

        k: []

        for k in TOP_K_VALUES

    }

    mrr_scores = []

    query_results = []

    # --------------------------------------------------------
    # EVALUATE
    # --------------------------------------------------------

    print(
        "\nEvaluating queries..."
    )

    total_queries = len(
        valid_queries
    )

    for i, (
        query_id,
        query_text
    ) in enumerate(
        valid_queries.items(),
        start=1
    ):

        relevant_documents = (
            valid_qrels[query_id]
        )

        # Encode query

        query_embedding = model.encode(
            [query_text],
            normalize_embeddings=True
        ).astype(
            "float32"
        )

        # Retrieve unique SciFact documents

        retrieved_documents = (
            retrieve_scifact_documents(
                query_embedding,
                index,
                metadata,
                top_k=10
            )
        )

        query_metrics = {}

        # ----------------------------------------------------
        # RECALL@K
        # ----------------------------------------------------

        for k in TOP_K_VALUES:

            recall = calculate_recall_at_k(
                retrieved_documents,
                relevant_documents,
                k
            )

            recall_scores[k].append(
                recall
            )

            query_metrics[
                f"Recall@{k}"
            ] = recall

        # ----------------------------------------------------
        # MRR@10
        # ----------------------------------------------------

        mrr = calculate_mrr(
            retrieved_documents,
            relevant_documents,
            10
        )

        mrr_scores.append(
            mrr
        )

        query_metrics[
            "MRR@10"
        ] = mrr

        # ----------------------------------------------------
        # STORE QUERY RESULT
        # ----------------------------------------------------

        query_results.append({

            "query_id": query_id,

            "query": query_text,

            "relevant_documents": sorted(
                list(relevant_documents)
            ),

            "retrieved_documents": (
                retrieved_documents
            ),

            "metrics": query_metrics

        })

        print(
            f"Processed {i}/{total_queries}"
        )

    # --------------------------------------------------------
    # FINAL METRICS
    # --------------------------------------------------------

    final_metrics = {}

    for k in TOP_K_VALUES:

        final_metrics[
            f"Recall@{k}"
        ] = float(
            np.mean(
                recall_scores[k]
            )
        )

    final_metrics[
        "MRR@10"
    ] = float(
        np.mean(
            mrr_scores
        )
    )

    # --------------------------------------------------------
    # DISPLAY RESULTS
    # --------------------------------------------------------

    print("\n" + "=" * 70)
    print("SCIFACT RETRIEVAL RESULTS")
    print("=" * 70)

    print(
        f"Evaluation queries: "
        f"{len(valid_queries)}"
    )

    print(
        f"Indexed SciFact documents: "
        f"{len(indexed_scifact_documents)}"
    )

    print()

    for metric, value in final_metrics.items():

        print(
            f"{metric}: {value:.4f}"
        )

    # --------------------------------------------------------
    # SAVE RESULTS
    # --------------------------------------------------------

    output = {

        "dataset": "BEIR/SciFact",

        "embedding_model": MODEL_NAME,

        "faiss_index": "IndexFlatIP",

        "total_vectors": int(
            index.ntotal
        ),

        "indexed_scifact_documents": len(
            indexed_scifact_documents
        ),

        "evaluation_queries": len(
            valid_queries
        ),

        "metrics": final_metrics,

        "query_results": query_results

    }

    with open(
        OUTPUT_PATH,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=4
        )

    print(
        "\nResults saved to:"
    )

    print(
        OUTPUT_PATH
    )


if __name__ == "__main__":

    main()