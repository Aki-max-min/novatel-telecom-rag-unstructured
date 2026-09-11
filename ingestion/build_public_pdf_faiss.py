import json
from pathlib import Path

import faiss
import numpy as np


# ============================================================
# PATH CONFIGURATION
# ============================================================

VECTORSTORE_DIR = Path(
    "data/experiments/public_pdfs/vectorstore"
)

EMBEDDINGS_PATH = (
    VECTORSTORE_DIR / "embeddings.npy"
)

METADATA_PATH = (
    VECTORSTORE_DIR / "chunk_metadata.json"
)

INDEX_PATH = (
    VECTORSTORE_DIR / "faiss.index"
)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NOVATEL PUBLIC PDF FAISS INDEX BUILDER")
    print("=" * 70)


    # --------------------------------------------------------
    # CHECK FILES
    # --------------------------------------------------------

    if not EMBEDDINGS_PATH.exists():

        print(
            "\nERROR: Embeddings file not found:"
        )

        print(EMBEDDINGS_PATH)

        return


    if not METADATA_PATH.exists():

        print(
            "\nERROR: Metadata file not found:"
        )

        print(METADATA_PATH)

        return


    # --------------------------------------------------------
    # LOAD EMBEDDINGS
    # --------------------------------------------------------

    print("\nLoading embeddings...")

    embeddings = np.load(
        EMBEDDINGS_PATH
    ).astype(np.float32)


    # --------------------------------------------------------
    # LOAD METADATA
    # --------------------------------------------------------

    print("Loading metadata...")

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)


    print(
        f"\nEmbeddings shape: "
        f"{embeddings.shape}"
    )

    print(
        f"Metadata records: "
        f"{len(metadata)}"
    )


    # --------------------------------------------------------
    # VALIDATE
    # --------------------------------------------------------

    if embeddings.shape[0] != len(metadata):

        print(
            "\nERROR: Embedding count does not "
            "match metadata count."
        )

        return


    if embeddings.ndim != 2:

        print(
            "\nERROR: Embeddings must be a "
            "2-dimensional array."
        )

        return


    # --------------------------------------------------------
    # CREATE FAISS INDEX
    # --------------------------------------------------------

    dimension = embeddings.shape[1]

    print(
        "\nCreating FAISS IndexFlatIP..."
    )

    index = faiss.IndexFlatIP(
        dimension
    )

    index.add(
        embeddings
    )


    # --------------------------------------------------------
    # SAVE INDEX
    # --------------------------------------------------------

    faiss.write_index(
        index,
        str(INDEX_PATH)
    )


    # ========================================================
    # RESULTS
    # ========================================================

    print("\n" + "=" * 70)
    print("PUBLIC PDF FAISS INDEX RESULT")
    print("=" * 70)

    print(
        f"Index type: "
        f"{type(index).__name__}"
    )

    print(
        f"Vector dimension: "
        f"{dimension}"
    )

    print(
        f"Vectors stored: "
        f"{index.ntotal}"
    )

    print(
        f"Index saved to: "
        f"{INDEX_PATH}"
    )


if __name__ == "__main__":
    main()