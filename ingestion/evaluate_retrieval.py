import json
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer


BENCHMARK_PATH = Path(
    "ingestion/retrieval_benchmark.json"
)

INDEX_PATH = Path(
    "data/vectorstore/faiss.index"
)

METADATA_PATH = Path(
    "data/vectorstore/chunk_metadata.json"
)

MODEL_NAME = "all-MiniLM-L6-v2"


def main():

    print("=" * 80)
    print("NOVATEL RETRIEVAL EVALUATION")
    print("=" * 80)

    # --------------------------------------------------
    # Load benchmark
    # --------------------------------------------------

    with open(
        BENCHMARK_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        benchmark = json.load(f)

    # --------------------------------------------------
    # Load metadata
    # --------------------------------------------------

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)

    # --------------------------------------------------
    # Load FAISS
    # --------------------------------------------------

    index = faiss.read_index(
        str(INDEX_PATH)
    )

    # --------------------------------------------------
    # Load embedding model
    # --------------------------------------------------

    print(
        "Loading embedding model..."
    )

    model = SentenceTransformer(
        MODEL_NAME
    )

    print(
        "Benchmark questions:",
        len(benchmark)
    )

    print(
        "FAISS vectors:",
        index.ntotal
    )

    # --------------------------------------------------
    # Metrics
    # --------------------------------------------------

    top1_hits = 0
    top3_hits = 0
    top5_hits = 0

    category_top1 = 0
    category_top3 = 0
    category_top5 = 0

    results = []

    # --------------------------------------------------
    # Evaluate each question
    # --------------------------------------------------

    for item in benchmark:

        question = item["question"]

        expected_ids = set(
            item["expected_document_ids"]
        )

        expected_category = (
            item["category"]
        )

        query_embedding = model.encode(
            [question],
            convert_to_numpy=True,
            normalize_embeddings=True
        ).astype("float32")

        scores, indices = index.search(
            query_embedding,
            5
        )

        retrieved = []

        for score, idx in zip(
            scores[0],
            indices[0]
        ):

            doc = metadata[idx]

            retrieved.append(
                {
                    "document_id":
                        doc["document_id"],
                    "chunk_id":
                        doc["chunk_id"],
                    "category":
                        doc["category"],
                    "title":
                        doc["title"],
                    "score":
                        float(score)
                }
            )

        retrieved_ids = [
            x["document_id"]
            for x in retrieved
        ]

        retrieved_categories = [
            x["category"]
            for x in retrieved
        ]

        # Document-level matching
        hit1 = any(
            doc_id in expected_ids
            for doc_id in retrieved_ids[:1]
        )

        hit3 = any(
            doc_id in expected_ids
            for doc_id in retrieved_ids[:3]
        )

        hit5 = any(
            doc_id in expected_ids
            for doc_id in retrieved_ids[:5]
        )

        # Category-level matching
        cat1 = (
            expected_category
            in retrieved_categories[:1]
        )

        cat3 = (
            expected_category
            in retrieved_categories[:3]
        )

        cat5 = (
            expected_category
            in retrieved_categories[:5]
        )

        if hit1:
            top1_hits += 1

        if hit3:
            top3_hits += 1

        if hit5:
            top5_hits += 1

        if cat1:
            category_top1 += 1

        if cat3:
            category_top3 += 1

        if cat5:
            category_top5 += 1

        results.append(
            {
                "question_id":
                    item["question_id"],
                "category":
                    expected_category,
                "question":
                    question,
                "expected_document_ids":
                    list(expected_ids),
                "top5": retrieved,
                "document_hit_top1":
                    hit1,
                "document_hit_top3":
                    hit3,
                "document_hit_top5":
                    hit5,
                "category_hit_top1":
                    cat1,
                "category_hit_top3":
                    cat3,
                "category_hit_top5":
                    cat5
            }
        )

    total = len(benchmark)

    # --------------------------------------------------
    # Print summary
    # --------------------------------------------------

    print()
    print("=" * 80)
    print("DOCUMENT-LEVEL RETRIEVAL RESULTS")
    print("=" * 80)

    print(
        f"Top-1: {top1_hits}/{total} "
        f"({top1_hits / total * 100:.2f}%)"
    )

    print(
        f"Top-3: {top3_hits}/{total} "
        f"({top3_hits / total * 100:.2f}%)"
    )

    print(
        f"Top-5: {top5_hits}/{total} "
        f"({top5_hits / total * 100:.2f}%)"
    )

    print()
    print("=" * 80)
    print("CATEGORY-LEVEL RETRIEVAL RESULTS")
    print("=" * 80)

    print(
        f"Top-1: {category_top1}/{total} "
        f"({category_top1 / total * 100:.2f}%)"
    )

    print(
        f"Top-3: {category_top3}/{total} "
        f"({category_top3 / total * 100:.2f}%)"
    )

    print(
        f"Top-5: {category_top5}/{total} "
        f"({category_top5 / total * 100:.2f}%)"
    )

    # --------------------------------------------------
    # Print per-question results
    # --------------------------------------------------

    print()
    print("=" * 80)
    print("PER-QUESTION RESULTS")
    print("=" * 80)

    for result in results:

        top1 = result["top5"][0]

        status = (
            "PASS"
            if result["document_hit_top1"]
            else "MISS"
        )

        print(
            f"{status} | "
            f"{result['question_id']} | "
            f"{result['category']} | "
            f"Top-1: {top1['document_id']} | "
            f"Score: {top1['score']:.4f}"
        )

    # --------------------------------------------------
    # Save results
    # --------------------------------------------------

    output_path = Path(
        "data/vectorstore/"
        "retrieval_evaluation.json"
    )

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "total_questions": total,
                "document_metrics": {
                    "top1": top1_hits / total,
                    "top3": top3_hits / total,
                    "top5": top5_hits / total
                },
                "category_metrics": {
                    "top1":
                        category_top1 / total,
                    "top3":
                        category_top3 / total,
                    "top5":
                        category_top5 / total
                },
                "results": results
            },
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print(
        "Detailed evaluation saved to:",
        output_path
    )


if __name__ == "__main__":
    main()