import json
from pathlib import Path

import numpy as np


EMBEDDINGS_PATH = Path(
    "data/vectorstore/embeddings.npy"
)

METADATA_PATH = Path(
    "data/vectorstore/chunk_metadata.json"
)


def main():

    print("=" * 70)
    print("NOVATEL EMBEDDING VALIDATION")
    print("=" * 70)

    embeddings = np.load(
        EMBEDDINGS_PATH
    )

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        metadata = json.load(f)

    print(
        "Embedding shape:",
        embeddings.shape
    )

    print(
        "Embedding dtype:",
        embeddings.dtype
    )

    print(
        "Metadata records:",
        len(metadata)
    )

    errors = []

    # --------------------------------------------------
    # Shape
    # --------------------------------------------------

    if embeddings.shape != (
        len(metadata),
        384
    ):

        errors.append(
            "Embedding shape does not match "
            "metadata count / expected dimension."
        )

    # --------------------------------------------------
    # Data type
    # --------------------------------------------------

    if embeddings.dtype != np.float32:

        errors.append(
            f"Expected float32, got {embeddings.dtype}"
        )

    # --------------------------------------------------
    # NaN
    # --------------------------------------------------

    nan_count = np.isnan(
        embeddings
    ).sum()

    print(
        "NaN values:",
        int(nan_count)
    )

    if nan_count > 0:

        errors.append(
            "NaN values detected."
        )

    # --------------------------------------------------
    # Infinite values
    # --------------------------------------------------

    inf_count = np.isinf(
        embeddings
    ).sum()

    print(
        "Infinite values:",
        int(inf_count)
    )

    if inf_count > 0:

        errors.append(
            "Infinite values detected."
        )

    # --------------------------------------------------
    # Duplicate chunk IDs
    # --------------------------------------------------

    chunk_ids = [
        item["chunk_id"]
        for item in metadata
    ]

    unique_chunk_ids = set(
        chunk_ids
    )

    print(
        "Unique chunk IDs:",
        len(unique_chunk_ids)
    )

    if len(unique_chunk_ids) != len(
        chunk_ids
    ):

        errors.append(
            "Duplicate chunk IDs detected."
        )

    # --------------------------------------------------
    # Vector norms
    # --------------------------------------------------

    norms = np.linalg.norm(
        embeddings,
        axis=1
    )

    print(
        "Minimum vector norm:",
        float(norms.min())
    )

    print(
        "Maximum vector norm:",
        float(norms.max())
    )

    # Because normalize_embeddings=True
    # was used during embedding, norms should
    # be approximately 1.

    if not np.allclose(
        norms,
        1.0,
        atol=1e-3
    ):

        errors.append(
            "Embeddings are not properly normalised."
        )

    # --------------------------------------------------
    # Result
    # --------------------------------------------------

    print()

    if errors:

        print(
            "VALIDATION RESULT: FAILED"
        )

        print(
            "Errors:",
            len(errors)
        )

        for error in errors:

            print(
                "ERROR:",
                error
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