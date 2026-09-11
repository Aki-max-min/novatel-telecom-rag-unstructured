from pathlib import Path
import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Combined FAISS index
COMBINED_INDEX = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "combined_retrieval"
    / "vectorstore"
    / "faiss.index"
)

# Combined metadata
COMBINED_METADATA = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "combined_retrieval"
    / "vectorstore"
    / "chunk_metadata.json"
)

# Existing synthetic benchmark
SYNTHETIC_EVAL = (
    PROJECT_ROOT
    / "data"
    / "vectorstore"
    / "retrieval_evaluation.json"
)

# Existing public PDF benchmark
PUBLIC_EVAL = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "public_pdfs"
    / "public_pdf_queries.json"
)

# E9 output
OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "combined_retrieval"
)

OUTPUT_FILE = (
    OUTPUT_DIR
    / "combined_retrieval_evaluation.json"
)


# ============================================================
# SETTINGS
# ============================================================

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Retrieve top 10 chunks from the complete combined index.
TOP_K = 10

K_VALUES = [1, 3, 5, 10]


# ============================================================
# JSON HELPER
# ============================================================

def load_json(path):

    print(f"Loading: {path}")

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


# ============================================================
# ID NORMALIZATION
# ============================================================

def normalize_id(value):

    if value is None:
        return None

    return str(value).strip().upper()


# ============================================================
# METADATA HELPERS
# ============================================================

def get_document_id(record):
    """
    Extract the document ID from a combined metadata record.
    """

    for key in [
        "document_id",
        "doc_id",
        "document",
    ]:

        if key in record:
            return normalize_id(
                record[key]
            )

    return None


# ============================================================
# BENCHMARK PARSERS
# ============================================================

def extract_synthetic_queries(data):
    """
    Existing synthetic benchmark format:

    {
        "total_questions": 29,
        "document_metrics": {...},
        "category_metrics": {...},
        "retrieval_precision": {...},
        "contextual_relevancy": {...},
        "results": [...]
    }

    The actual evaluation questions are under:
        data["results"]
    """

    if isinstance(data, dict):

        if (
            "results" in data
            and isinstance(data["results"], list)
        ):
            return data["results"]

    if isinstance(data, list):
        return data

    raise ValueError(
        "Could not find synthetic query list "
        "in evaluation file."
    )


def extract_public_queries(data):
    """
    Existing public benchmark is expected to contain
    the 30 query records.

    Supports either:
        list
    or:
        {"results": [...]}
        {"queries": [...]}
        {"questions": [...]}
    """

    if isinstance(data, dict):

        for key in [
            "results",
            "queries",
            "questions",
            "evaluation",
        ]:

            if (
                key in data
                and isinstance(data[key], list)
            ):
                return data[key]

    if isinstance(data, list):
        return data

    raise ValueError(
        "Could not find public query list "
        "in evaluation file."
    )


# ============================================================
# QUERY TEXT
# ============================================================

def get_query_text(item):
    """
    Synthetic benchmark uses:
        question

    Public benchmark uses:
        query
    """

    for key in [
        "question",
        "query",
        "text",
    ]:

        if key in item:
            return str(item[key])

    raise ValueError(
        f"Could not find query text in benchmark item:\n{item}"
    )


# ============================================================
# GROUND TRUTH
# ============================================================

def get_expected_ids(item):
    """
    Synthetic benchmark:
        expected_document_ids

    Public benchmark:
        relevant_documents
    """

    for key in [
        "expected_document_ids",
        "relevant_document_ids",
        "relevant_documents",
        "expected_docs",
        "ground_truth",
    ]:

        if key in item:

            value = item[key]

            if isinstance(value, str):

                return {
                    normalize_id(value)
                }

            if isinstance(value, list):

                return {
                    normalize_id(x)
                    for x in value
                }

    raise ValueError(
        "Could not find expected document IDs "
        f"in benchmark item:\n{item}"
    )


# ============================================================
# RECIPROCAL RANK
# ============================================================

def reciprocal_rank(
    retrieved,
    expected
):

    for rank, document_id in enumerate(
        retrieved,
        start=1
    ):

        if document_id in expected:
            return 1.0 / rank

    return 0.0


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(results):

    total = len(results)

    if total == 0:

        return {
            "R@1": 0.0,
            "R@3": 0.0,
            "R@5": 0.0,
            "R@10": 0.0,
            "MRR@10": 0.0,
        }

    metrics = {}

    # --------------------------------------------------------
    # Recall@K
    # --------------------------------------------------------

    for k in K_VALUES:

        hits = 0

        for result in results:

            retrieved = (
                result[
                    "retrieved_document_ids"
                ][:k]
            )

            expected = set(
                result[
                    "expected_document_ids"
                ]
            )

            if any(
                document_id in expected
                for document_id in retrieved
            ):

                hits += 1

        metrics[f"R@{k}"] = (
            hits / total
        )

    # --------------------------------------------------------
    # MRR@10
    # --------------------------------------------------------

    mrr = sum(
        reciprocal_rank(
            result[
                "retrieved_document_ids"
            ],
            set(
                result[
                    "expected_document_ids"
                ]
            )
        )
        for result in results
    ) / total

    metrics["MRR@10"] = mrr

    return metrics


# ============================================================
# EVALUATE BENCHMARK
# ============================================================

def evaluate_queries(
    queries,
    source_name,
    index,
    metadata,
    model
):
    """
    Evaluate a benchmark against the COMPLETE
    1545-chunk combined FAISS index.

    Synthetic queries are NOT restricted to synthetic
    chunks.

    Public queries are NOT restricted to public chunks.

    This is important because E9 tests whether a combined
    corpus changes retrieval behavior.
    """

    print("\n" + "=" * 70)
    print(
        f"EVALUATING: {source_name.upper()}"
    )
    print("=" * 70)

    results = []

    total_queries = len(queries)

    for query_number, item in enumerate(
        queries,
        start=1
    ):

        query = get_query_text(item)

        expected = get_expected_ids(item)

        # ----------------------------------------------------
        # Encode query
        # ----------------------------------------------------

        query_vector = model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype(
            np.float32
        )

        # ----------------------------------------------------
        # Search COMPLETE combined index
        # ----------------------------------------------------

        scores, indices = index.search(
            query_vector,
            TOP_K
        )

        retrieved_document_ids = []

        retrieved_chunks = []

        for score, index_position in zip(
            scores[0],
            indices[0]
        ):

            if index_position < 0:
                continue

            record = metadata[
                int(index_position)
            ]

            document_id = get_document_id(
                record
            )

            if document_id is None:
                continue

            # ------------------------------------------------
            # Convert chunk ranking into document ranking.
            #
            # Multiple chunks from the same document should
            # count as one retrieved document.
            # ------------------------------------------------

            if (
                document_id
                in retrieved_document_ids
            ):
                continue

            retrieved_document_ids.append(
                document_id
            )

            retrieved_chunks.append(
                {
                    "document_id":
                        document_id,

                    "chunk_id":
                        record.get(
                            "chunk_id"
                        ),

                    "source_corpus":
                        record.get(
                            "source_corpus"
                        ),

                    "score":
                        float(score),
                }
            )

        # ----------------------------------------------------
        # Find first relevant document
        # ----------------------------------------------------

        hit_rank = None

        for rank, document_id in enumerate(
            retrieved_document_ids,
            start=1
        ):

            if document_id in expected:

                hit_rank = rank
                break

        # ----------------------------------------------------
        # Save query result
        # ----------------------------------------------------

        results.append(
            {
                "query_number":
                    query_number,

                "question_id":
                    item.get(
                        "question_id",
                        item.get(
                            "query_id"
                        )
                    ),

                "query":
                    query,

                "expected_document_ids":
                    sorted(expected),

                "retrieved_document_ids":
                    retrieved_document_ids,

                "hit_rank":
                    hit_rank,

                "retrieved_chunks":
                    retrieved_chunks,
            }
        )

        if (
            query_number % 5 == 0
            or query_number == total_queries
        ):

            print(
                f"Processed "
                f"{query_number}/{total_queries}"
            )

    # --------------------------------------------------------
    # Calculate metrics
    # --------------------------------------------------------

    metrics = calculate_metrics(
        results
    )

    print("\nMetrics:")

    for metric, value in metrics.items():

        print(
            f"  {metric:8s}: {value:.4f}"
        )

    return {
        "source":
            source_name,

        "total_queries":
            total_queries,

        "metrics":
            metrics,

        "results":
            results,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print(
        "E9 — COMBINED SYNTHETIC + PUBLIC RETRIEVAL EVALUATION"
    )
    print("=" * 70)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # ========================================================
    # 1. LOAD COMBINED INDEX
    # ========================================================

    print(
        "\n[1/7] Loading combined FAISS index..."
    )

    index = faiss.read_index(
        str(COMBINED_INDEX)
    )

    metadata = load_json(
        COMBINED_METADATA
    )

    print(
        f"Index vectors : {index.ntotal}"
    )

    print(
        f"Dimension     : {index.d}"
    )

    print(
        f"Metadata      : {len(metadata)}"
    )

    # --------------------------------------------------------
    # Validate index / metadata
    # --------------------------------------------------------

    if index.ntotal != len(metadata):

        raise ValueError(
            "Combined index/metadata mismatch: "
            f"{index.ntotal} vs "
            f"{len(metadata)}"
        )

    # ========================================================
    # SOURCE COUNTS
    # ========================================================

    synthetic_count = sum(
        1
        for record in metadata
        if record.get(
            "source_corpus"
        ) == "synthetic"
    )

    public_count = sum(
        1
        for record in metadata
        if record.get(
            "source_corpus"
        ) == "public"
    )

    print(
        f"Synthetic chunks : "
        f"{synthetic_count}"
    )

    print(
        f"Public chunks    : "
        f"{public_count}"
    )

    # --------------------------------------------------------
    # Validate expected corpus size
    # --------------------------------------------------------

    if synthetic_count != 383:

        raise ValueError(
            "Expected 383 synthetic chunks, "
            f"found {synthetic_count}."
        )

    if public_count != 1162:

        raise ValueError(
            "Expected 1162 public chunks, "
            f"found {public_count}."
        )

    if index.ntotal != 1545:

        raise ValueError(
            "Expected 1545 combined chunks, "
            f"found {index.ntotal}."
        )

    # ========================================================
    # 2. LOAD EMBEDDING MODEL
    # ========================================================

    print(
        "\n[2/7] Loading embedding model..."
    )

    model = SentenceTransformer(
        MODEL_NAME
    )

    print(
        f"Model: {MODEL_NAME}"
    )

    # ========================================================
    # 3. LOAD BENCHMARKS
    # ========================================================

    print(
        "\n[3/7] Loading evaluation benchmarks..."
    )

    synthetic_data = load_json(
        SYNTHETIC_EVAL
    )

    public_data = load_json(
        PUBLIC_EVAL
    )

    synthetic_queries = (
        extract_synthetic_queries(
            synthetic_data
        )
    )

    public_queries = (
        extract_public_queries(
            public_data
        )
    )

    print(
        f"Synthetic queries : "
        f"{len(synthetic_queries)}"
    )

    print(
        f"Public queries    : "
        f"{len(public_queries)}"
    )

    # --------------------------------------------------------
    # Validate benchmark sizes
    # --------------------------------------------------------

    if len(synthetic_queries) != 29:

        raise ValueError(
            "Expected 29 synthetic queries, "
            f"found {len(synthetic_queries)}."
        )

    if len(public_queries) != 30:

        raise ValueError(
            "Expected 30 public queries, "
            f"found {len(public_queries)}."
        )

    # ========================================================
    # 4. SYNTHETIC BENCHMARK
    # ========================================================

    print(
        "\n[4/7] Running synthetic benchmark..."
    )

    synthetic_results = evaluate_queries(
        queries=synthetic_queries,
        source_name="synthetic",
        index=index,
        metadata=metadata,
        model=model,
    )

    # ========================================================
    # 5. PUBLIC BENCHMARK
    # ========================================================

    print(
        "\n[5/7] Running public benchmark..."
    )

    public_results = evaluate_queries(
        queries=public_queries,
        source_name="public",
        index=index,
        metadata=metadata,
        model=model,
    )

    # ========================================================
    # 6. OVERALL METRICS
    # ========================================================

    print(
        "\n[6/7] Calculating overall metrics..."
    )

    all_results = (
        synthetic_results["results"]
        +
        public_results["results"]
    )

    overall_metrics = calculate_metrics(
        all_results
    )

    print(
        "\nOverall combined metrics:"
    )

    for metric, value in (
        overall_metrics.items()
    ):

        print(
            f"  {metric:8s}: {value:.4f}"
        )

    # ========================================================
    # 7. SAVE RESULTS
    # ========================================================

    print(
        "\n[7/7] Saving E9 results..."
    )

    output = {

        "experiment":
            "E9",

        "description":
            (
                "Combined Synthetic + Public "
                "Telecom retrieval baseline"
            ),

        "index": {

            "total_chunks":
                index.ntotal,

            "dimension":
                index.d,

            "synthetic_chunks":
                synthetic_count,

            "public_chunks":
                public_count,
        },

        "model":
            MODEL_NAME,

        "top_k":
            TOP_K,

        "benchmarks": {

            "synthetic_queries":
                len(synthetic_queries),

            "public_queries":
                len(public_queries),

            "total_queries":
                len(all_results),
        },

        "synthetic":
            synthetic_results,

        "public":
            public_results,

        "overall": {

            "total_queries":
                len(all_results),

            "metrics":
                overall_metrics,
        },
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False
        )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print(
        "E9 EVALUATION COMPLETE"
    )
    print("=" * 70)

    print(
        "\nCorpus:"
    )

    print(
        f"  Synthetic chunks : "
        f"{synthetic_count}"
    )

    print(
        f"  Public chunks    : "
        f"{public_count}"
    )

    print(
        f"  Combined chunks  : "
        f"{index.ntotal}"
    )

    print(
        "\nQueries:"
    )

    print(
        f"  Synthetic : "
        f"{len(synthetic_queries)}"
    )

    print(
        f"  Public    : "
        f"{len(public_queries)}"
    )

    print(
        f"  Total     : "
        f"{len(all_results)}"
    )

    print(
        "\nOverall metrics:"
    )

    for metric, value in (
        overall_metrics.items()
    ):

        print(
            f"  {metric:8s}: {value:.4f}"
        )

    print(
        "\nResults saved to:"
    )

    print(
        OUTPUT_FILE
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()