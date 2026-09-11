import json
from pathlib import Path

from retriever import ColPaliRetriever


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EVAL_FILE = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "public_pdfs"
    / "public_pdf_retrieval_evaluation.json"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "public_pdfs"
    / "colpali"
    / "colpali_retrieval_evaluation.json"
)


# ============================================================
# METRIC FUNCTIONS
# ============================================================

def recall_at_k(retrieved, relevant, k):

    return 1.0 if any(
        document in relevant
        for document in retrieved[:k]
    ) else 0.0


def reciprocal_rank_at_k(retrieved, relevant, k):

    for rank, document in enumerate(
        retrieved[:k],
        start=1
    ):

        if document in relevant:
            return 1.0 / rank

    return 0.0


# ============================================================
# DOCUMENT ID NORMALIZATION
# ============================================================

def normalize_document_id(document_id):

    """
    Convert ColPali metadata document IDs such as:

        01_telecom_consumers_protection

    into the benchmark format:

        PUBLIC_PDF_01_TELECOM_CONSUMERS_PROTECTION
    """

    return "PUBLIC_PDF_" + document_id.upper()


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("COLPALI DOCUMENT-LEVEL EVALUATION")
    print("=" * 70)

    # --------------------------------------------------------
    # Load existing benchmark
    # --------------------------------------------------------

    print("\nLoading evaluation benchmark...")

    with open(
        EVAL_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        evaluation_data = json.load(f)

    queries = evaluation_data["query_results"]

    print(
        f"Evaluation queries: {len(queries)}"
    )

    print(
        f"Ground-truth documents: "
        f"{evaluation_data['total_documents']}"
    )

    # --------------------------------------------------------
    # Initialize ColPali
    # --------------------------------------------------------

    retriever = ColPaliRetriever()

    total_pages = len(retriever.embeddings)

    print(
        f"\nColPali pages available: {total_pages}"
    )

    # --------------------------------------------------------
    # Metric accumulators
    # --------------------------------------------------------

    total_r1 = 0.0
    total_r3 = 0.0
    total_r5 = 0.0
    total_r10 = 0.0
    total_mrr = 0.0

    query_results = []

    # ========================================================
    # EVALUATE ALL QUERIES
    # ========================================================

    for query_number, item in enumerate(
        queries,
        start=1
    ):

        query_id = item["query_id"]
        query = item["query"]

        relevant_documents = (
            item["relevant_documents"]
        )

        print()
        print("-" * 70)
        print(
            f"[{query_number}/{len(queries)}] "
            f"{query_id}"
        )
        print(f"Query: {query}")

        # ----------------------------------------------------
        # Search ALL pages
        # ----------------------------------------------------
        #
        # Important:
        # search(top_k=10) would only return 10 pages.
        #
        # We need all pages so that we can aggregate:
        #
        # page scores -> document scores
        #
        # before calculating document-level Recall/MRR.
        # ----------------------------------------------------

        page_results = retriever.search(
            query,
            top_k=total_pages
        )

        # ----------------------------------------------------
        # Aggregate page scores by document
        #
        # Each document receives its BEST page score.
        # ----------------------------------------------------

        document_scores = {}

        for result in page_results:

            raw_document_id = result["document_id"]

            document_id = normalize_document_id(
                raw_document_id
            )

            score = result["score"]

            if (
                document_id not in document_scores
                or score > document_scores[document_id]
            ):

                document_scores[document_id] = score

        # ----------------------------------------------------
        # Rank documents
        # ----------------------------------------------------

        ranked_documents = sorted(
            document_scores.items(),
            key=lambda item: item[1],
            reverse=True
        )

        retrieved_documents = [
            document_id
            for document_id, score
            in ranked_documents
        ]

        # Only the top 10 documents matter for evaluation
        retrieved_documents = (
            retrieved_documents[:10]
        )

        # ----------------------------------------------------
        # Calculate metrics
        # ----------------------------------------------------

        r1 = recall_at_k(
            retrieved_documents,
            relevant_documents,
            1
        )

        r3 = recall_at_k(
            retrieved_documents,
            relevant_documents,
            3
        )

        r5 = recall_at_k(
            retrieved_documents,
            relevant_documents,
            5
        )

        r10 = recall_at_k(
            retrieved_documents,
            relevant_documents,
            10
        )

        rr10 = reciprocal_rank_at_k(
            retrieved_documents,
            relevant_documents,
            10
        )

        # ----------------------------------------------------
        # Accumulate
        # ----------------------------------------------------

        total_r1 += r1
        total_r3 += r3
        total_r5 += r5
        total_r10 += r10
        total_mrr += rr10

        # ----------------------------------------------------
        # Save query result
        # ----------------------------------------------------

        query_result = {
            "query_id": query_id,
            "query": query,
            "relevant_documents": relevant_documents,
            "retrieved_documents": retrieved_documents,
            "metrics": {
                "Recall@1": r1,
                "Recall@3": r3,
                "Recall@5": r5,
                "Recall@10": r10,
                "ReciprocalRank@10": rr10
            }
        }

        query_results.append(query_result)

        # ----------------------------------------------------
        # Display
        # ----------------------------------------------------

        print(
            f"Relevant: {relevant_documents}"
        )

        print(
            f"Top documents:"
        )

        for rank, document in enumerate(
            retrieved_documents,
            start=1
        ):

            print(
                f"  {rank}. {document}"
            )

        print(
            f"Metrics: "
            f"R@1={r1:.3f} | "
            f"R@3={r3:.3f} | "
            f"R@5={r5:.3f} | "
            f"R@10={r10:.3f} | "
            f"RR@10={rr10:.3f}"
        )

    # ========================================================
    # OVERALL METRICS
    # ========================================================

    n = len(queries)

    overall_metrics = {

        "Recall@1": total_r1 / n,

        "Recall@3": total_r3 / n,

        "Recall@5": total_r5 / n,

        "Recall@10": total_r10 / n,

        "MRR@10": total_mrr / n
    }

    # ========================================================
    # DISPLAY FINAL RESULTS
    # ========================================================

    print()
    print("=" * 70)
    print("COLPALI RESULTS")
    print("=" * 70)

    for metric, value in overall_metrics.items():

        print(
            f"{metric}: {value:.4f}"
        )

    # ========================================================
    # SAVE RESULTS
    # ========================================================

    output = {

        "dataset":
            "Real-World Public Telecom PDFs",

        "evaluation_type":
            "Document-level ColPali retrieval evaluation",

        "embedding_model":
            "vidore/colpali-v1.3-hf",

        "total_documents":
            evaluation_data["total_documents"],

        "total_pages":
            total_pages,

        "evaluation_queries":
            n,

        "aggregation":
            "Maximum page score per document",

        "metrics":
            overall_metrics,

        "query_results":
            query_results
    }

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2
        )

    print()
    print("Evaluation saved to:")

    print(OUTPUT_FILE)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()