import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


# ============================================================
# PATH CONFIGURATION
# ============================================================

CHUNKS_DIR = Path(
    "data/experiments/public_pdfs/chunks"
)

OUTPUT_DIR = Path(
    "data/experiments/public_pdfs/vectorstore"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


EMBEDDINGS_PATH = (
    OUTPUT_DIR / "embeddings.npy"
)

METADATA_PATH = (
    OUTPUT_DIR / "chunk_metadata.json"
)


MODEL_NAME = "all-MiniLM-L6-v2"

BATCH_SIZE = 32


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NOVATEL PUBLIC PDF CHUNK EMBEDDING")
    print("=" * 70)


    # --------------------------------------------------------
    # FIND CHUNKS
    # --------------------------------------------------------

    chunk_files = sorted(
        CHUNKS_DIR.glob("*.json")
    )

    print(
        f"\nChunks discovered: "
        f"{len(chunk_files)}"
    )


    if not chunk_files:

        print(
            "\nERROR: No chunk files found."
        )

        return


    # --------------------------------------------------------
    # LOAD CHUNKS
    # --------------------------------------------------------

    texts = []
    metadata = []


    print("\nLoading chunks...")


    for chunk_file in chunk_files:

        with open(
            chunk_file,
            "r",
            encoding="utf-8"
        ) as f:

            chunk = json.load(f)


        text = chunk.get(
            "text",
            ""
        ).strip()


        if not text:

            print(
                f"WARNING: Empty chunk skipped: "
                f"{chunk_file.name}"
            )

            continue


        texts.append(text)


        # Store complete metadata
        metadata.append(
            chunk
        )


    print(
        f"Chunks loaded for embedding: "
        f"{len(texts)}"
    )


    # --------------------------------------------------------
    # LOAD EMBEDDING MODEL
    # --------------------------------------------------------

    print(
        f"\nLoading embedding model: "
        f"{MODEL_NAME}"
    )


    model = SentenceTransformer(
        MODEL_NAME
    )


    # --------------------------------------------------------
    # GENERATE EMBEDDINGS
    # --------------------------------------------------------

    print(
        "\nGenerating embeddings..."
    )


    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True
    )


    embeddings = np.array(
        embeddings,
        dtype=np.float32
    )


    # --------------------------------------------------------
    # SAVE EMBEDDINGS
    # --------------------------------------------------------

    np.save(
        EMBEDDINGS_PATH,
        embeddings
    )


    # --------------------------------------------------------
    # SAVE METADATA
    # --------------------------------------------------------

    with open(
        METADATA_PATH,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            metadata,
            f,
            indent=2,
            ensure_ascii=False
        )


    # ========================================================
    # RESULTS
    # ========================================================

    print("\n" + "=" * 70)
    print("PUBLIC PDF EMBEDDING RESULT")
    print("=" * 70)

    print(
        f"Embeddings shape: "
        f"{embeddings.shape}"
    )

    print(
        f"Data type: "
        f"{embeddings.dtype}"
    )

    print(
        f"Metadata records: "
        f"{len(metadata)}"
    )

    print(
        f"Embeddings saved to: "
        f"{EMBEDDINGS_PATH}"
    )

    print(
        f"Metadata saved to: "
        f"{METADATA_PATH}"
    )


if __name__ == "__main__":
    main()