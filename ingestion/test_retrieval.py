import json
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer


INDEX_PATH = Path(
    "data/vectorstore/faiss.index"
)

METADATA_PATH = Path(
    "data/vectorstore/chunk_metadata.json"
)

MODEL_NAME = "all-MiniLM-L6-v2"


def main():

    query = (
        "I no longer have access to my old phone number. "
        "How can I change the number linked to my account?"
    )

    print("=" * 70)
    print("NOVATEL SEMANTIC RETRIEVAL TEST")
    print("=" * 70)

    print()
    print("Query:")
    print(query)

    # Load model
    model = SentenceTransformer(
        MODEL_NAME
    )

    # Load FAISS index
    index = faiss.read_index(
        str(INDEX_PATH)
    )

    # Load metadata
    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)

    # Embed query
    query_embedding = model.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True
    ).astype("float32")

    # Search
    scores, indices = index.search(
        query_embedding,
        5
    )

    print()
    print("=" * 70)
    print("TOP 5 RESULTS")
    print("=" * 70)

    for rank, (score, idx) in enumerate(
        zip(scores[0], indices[0]),
        start=1
    ):

        item = metadata[idx]

        print()
        print(f"Rank: {rank}")
        print(
            f"Score: {score:.4f}"
        )
        print(
            f"Chunk ID: {item['chunk_id']}"
        )
        print(
            f"Document ID: {item['document_id']}"
        )
        print(
            f"Title: {item['title']}"
        )
        print(
            f"Type: {item['document_type']}"
        )
        print(
            f"Category: {item['category']}"
        )
        print(
            f"Department: {item['department']}"
        )


if __name__ == "__main__":
    main()