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
    print("NOVATEL PUBLIC PDF EMBEDDING VALIDATION")
    print("=" * 70)

    errors = []


    # --------------------------------------------------------
    # CHECK FILES
    # --------------------------------------------------------

    for path in [
        EMBEDDINGS_PATH,
        METADATA_PATH,
        INDEX_PATH
    ]:

        if not path.exists():

            errors.append(
                f"Missing file: {path}"
            )


    if errors:

        print("\nVALIDATION RESULT: FAILED")

        for error in errors:
            print(f"- {error}")

        return


    # --------------------------------------------------------
    # LOAD EMBEDDINGS
    # --------------------------------------------------------

    embeddings = np.load(
        EMBEDDINGS_PATH
    )


    # --------------------------------------------------------
    # LOAD METADATA
    # --------------------------------------------------------

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)


    # --------------------------------------------------------
    # LOAD FAISS INDEX
    # --------------------------------------------------------

    index = faiss.read_index(
        str(INDEX_PATH)
    )


    # --------------------------------------------------------
    # BASIC VALIDATION
    # --------------------------------------------------------

    embedding_count = embeddings.shape[0]

    metadata_count = len(metadata)

    index_count = index.ntotal


    if embedding_count != metadata_count:

        errors.append(
            "Embedding count does not match "
            "metadata count."
        )


    if embedding_count != index_count:

        errors.append(
            "Embedding count does not match "
            "FAISS index count."
        )


    # --------------------------------------------------------
    # NaN / INFINITE CHECK
    # --------------------------------------------------------

    nan_count = int(
        np.isnan(embeddings).sum()
    )

    inf_count = int(
        np.isinf(embeddings).sum()
    )


    if nan_count > 0:

        errors.append(
            f"NaN values found: {nan_count}"
        )


    if inf_count > 0:

        errors.append(
            f"Infinite values found: {inf_count}"
        )


    # --------------------------------------------------------
    # VECTOR NORMS
    # --------------------------------------------------------

    norms = np.linalg.norm(
        embeddings,
        axis=1
    )

    min_norm = float(
        norms.min()
    )

    max_norm = float(
        norms.max()
    )


    # --------------------------------------------------------
    # CHUNK ID UNIQUENESS
    # --------------------------------------------------------

    chunk_ids = [
        item.get("chunk_id")
        for item in metadata
    ]

    unique_chunk_ids = len(
        set(chunk_ids)
    )


    if unique_chunk_ids != metadata_count:

        errors.append(
            "Duplicate chunk IDs found."
        )


    # --------------------------------------------------------
    # RESULTS
    # --------------------------------------------------------

    print(
        f"\nEmbedding shape: "
        f"{embeddings.shape}"
    )

    print(
        f"Embedding dtype: "
        f"{embeddings.dtype}"
    )

    print(
        f"Metadata records: "
        f"{metadata_count}"
    )

    print(
        f"FAISS vectors: "
        f"{index_count}"
    )

    print(
        f"NaN values: "
        f"{nan_count}"
    )

    print(
        f"Infinite values: "
        f"{inf_count}"
    )

    print(
        f"Unique chunk IDs: "
        f"{unique_chunk_ids}"
    )

    print(
        f"Minimum vector norm: "
        f"{min_norm}"
    )

    print(
        f"Maximum vector norm: "
        f"{max_norm}"
    )


    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    print("\n" + "-" * 70)

    if errors:

        print(
            "VALIDATION RESULT: FAILED"
        )

        print(
            f"Errors: {len(errors)}"
        )

        for error in errors:

            print(
                f"- {error}"
            )

    else:

        print(
            "VALIDATION RESULT: PASSED"
        )

        print(
            "Errors: 0"
        )


if __name__ == "__main__":
    main()