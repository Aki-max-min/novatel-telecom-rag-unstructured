import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


CHUNK_DIR = Path(
    "data/processed/chunks"
)

OUTPUT_DIR = Path(
    "data/vectorstore"
)

MODEL_NAME = (
    "all-MiniLM-L6-v2"
)


def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    files = sorted(
        CHUNK_DIR.glob("*.json")
    )

    print("=" * 70)
    print("NOVATEL CHUNK EMBEDDING")
    print("=" * 70)

    print(
        "Chunks discovered:",
        len(files)
    )

    if not files:

        raise RuntimeError(
            "No chunk files found."
        )

    print()
    print(
        "Loading embedding model:",
        MODEL_NAME
    )

    model = SentenceTransformer(
        MODEL_NAME
    )

    texts = []
    metadata = []

    for file_path in files:

        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:

            chunk = json.load(f)

        text = chunk["text"].strip()

        if not text:

            raise ValueError(
                f"Empty chunk: {file_path}"
            )

        texts.append(text)

        metadata.append(
            {
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "chunk_index": chunk["chunk_index"],
                "title": chunk["title"],
                "document_type": chunk["document_type"],
                "category": chunk["category"],
                "department": chunk["department"],
                "customer_scope": chunk["customer_scope"],
                "version": chunk["version"],
                "last_updated": chunk["last_updated"],
                "source_authority": chunk["source_authority"],
                "related_ids": chunk["related_ids"],
                "tags": chunk["tags"],
                "file_path": chunk["file_path"],
                "file_type": chunk["file_type"],
            }
        )

    print(
        "Generating embeddings..."
    )

    embeddings = model.encode(
        texts,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True
    )

    embeddings = embeddings.astype(
        "float32"
    )

    embeddings_path = (
        OUTPUT_DIR
        / "embeddings.npy"
    )

    metadata_path = (
        OUTPUT_DIR
        / "chunk_metadata.json"
    )

    np.save(
        embeddings_path,
        embeddings
    )

    with open(
        metadata_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            metadata,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print("=" * 70)
    print("EMBEDDING RESULT")
    print("=" * 70)

    print(
        "Embeddings shape:",
        embeddings.shape
    )

    print(
        "Data type:",
        embeddings.dtype
    )

    print(
        "Metadata records:",
        len(metadata)
    )

    print(
        "Embeddings saved to:",
        embeddings_path
    )

    print(
        "Metadata saved to:",
        metadata_path
    )


if __name__ == "__main__":
    main()