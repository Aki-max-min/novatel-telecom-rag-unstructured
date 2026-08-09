import json
from pathlib import Path

import faiss
import numpy as np


EMBEDDINGS_PATH = Path(
    "data/vectorstore/embeddings.npy"
)

METADATA_PATH = Path(
    "data/vectorstore/chunk_metadata.json"
)

INDEX_PATH = Path(
    "data/vectorstore/faiss.index"
)


def main():

    print("=" * 70)
    print("NOVATEL FAISS INDEX BUILDER")
    print("=" * 70)

    # Load embeddings
    embeddings = np.load(
        EMBEDDINGS_PATH
    ).astype("float32")

    # Load metadata
    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)

    print(
        "Embeddings shape:",
        embeddings.shape
    )

    print(
        "Metadata records:",
        len(metadata)
    )

    # Safety check
    if len(embeddings) != len(metadata):

        raise ValueError(
            "Number of embeddings does not "
            "match number of metadata records."
        )

    # Create FAISS index
    dimension = embeddings.shape[1]

    index = faiss.IndexFlatIP(
        dimension
    )

    # Add vectors
    index.add(
        embeddings
    )

    # Save index
    faiss.write_index(
        index,
        str(INDEX_PATH)
    )

    print()
    print("=" * 70)
    print("FAISS INDEX RESULT")
    print("=" * 70)

    print(
        "Index type:",
        type(index).__name__
    )

    print(
        "Vector dimension:",
        index.d
    )

    print(
        "Vectors stored:",
        index.ntotal
    )

    print(
        "Index saved to:",
        INDEX_PATH
    )


if __name__ == "__main__":
    main()