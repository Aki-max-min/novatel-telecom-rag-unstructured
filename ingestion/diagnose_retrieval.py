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

TARGET_QUESTIONS = {
    "Q08",
    "Q16",
    "Q17"
}


def main():

    with open(
        BENCHMARK_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        benchmark = json.load(f)

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        metadata = json.load(f)

    index = faiss.read_index(
        str(INDEX_PATH)
    )

    model = SentenceTransformer(
        MODEL_NAME
    )

    print("=" * 80)
    print("NOVATEL RETRIEVAL MISS DIAGNOSTIC")
    print("=" * 80)

    for item in benchmark:

        if item["question_id"] not in TARGET_QUESTIONS:
            continue

        question = item["question"]

        expected_category = item["category"]

        expected_ids = set(
            item["expected_document_ids"]
        )

        query_embedding = model.encode(
            [question],
            convert_to_numpy=True,
            normalize_embeddings=True
        ).astype("float32")

        scores, indices = index.search(
            query_embedding,
            10
        )

        print()
        print("=" * 80)
        print(
            f"{item['question_id']} | "
            f"Expected Category: {expected_category}"
        )
        print()
        print("QUESTION:")
        print(question)

        print()
        print("EXPECTED DOCUMENTS:")
        for doc_id in expected_ids:
            print("  ", doc_id)

        print()
        print("TOP 10 RESULTS:")
        print("-" * 80)

        for rank, (score, idx) in enumerate(
            zip(scores[0], indices[0]),
            start=1
        ):

            doc = metadata[idx]

            doc_id = doc["document_id"]
            category = doc["category"]

            expected_doc = (
                doc_id in expected_ids
            )

            expected_cat = (
                category == expected_category
            )

            if expected_doc:
                marker = "DOCUMENT MATCH"
            elif expected_cat:
                marker = "CATEGORY MATCH"
            else:
                marker = ""

            print(
                f"{rank:2}. "
                f"{doc_id:35} "
                f"score={score:.4f} "
                f"category={category:4} "
                f"{marker}"
            )

            print(
                f"    {doc['title']}"
            )


if __name__ == "__main__":
    main()