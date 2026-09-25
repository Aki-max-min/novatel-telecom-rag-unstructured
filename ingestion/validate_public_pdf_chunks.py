import json
from pathlib import Path


# ============================================================
# PATH CONFIGURATION
# ============================================================

CHUNKS_DIR = Path(
    "data/experiments/public_pdfs/chunks"
)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NOVATEL PUBLIC PDF CHUNK VALIDATION")
    print("=" * 70)

    if not CHUNKS_DIR.exists():

        print("\nERROR: Chunks directory not found:")
        print(CHUNKS_DIR)

        return

    chunk_files = sorted(
        CHUNKS_DIR.glob("*.json")
    )

    print(f"\nChunks discovered: {len(chunk_files)}")

    if not chunk_files:

        print("\nERROR: No chunks found.")
        return


    errors = []

    chunk_ids = set()
    document_ids = set()

    empty_chunks = 0

    word_counts = []

    missing_metadata = 0


    required_fields = [
        "chunk_id",
        "document_id",
        "chunk_index",
        "text",
        "title",
        "document_type",
        "category",
        "department",
        "customer_scope",
        "version",
        "last_updated",
        "source_authority"
    ]


    for chunk_file in chunk_files:

        try:

            with open(
                chunk_file,
                "r",
                encoding="utf-8"
            ) as f:

                chunk = json.load(f)


            # ----------------------------------------------
            # Check required fields
            # ----------------------------------------------

            for field in required_fields:

                if field not in chunk:

                    errors.append(
                        f"{chunk_file.name}: "
                        f"Missing field '{field}'"
                    )

                    missing_metadata += 1


            # ----------------------------------------------
            # Check chunk ID uniqueness
            # ----------------------------------------------

            chunk_id = chunk.get(
                "chunk_id"
            )

            if chunk_id in chunk_ids:

                errors.append(
                    f"Duplicate chunk ID: "
                    f"{chunk_id}"
                )

            else:

                chunk_ids.add(
                    chunk_id
                )


            # ----------------------------------------------
            # Track document IDs
            # ----------------------------------------------

            document_id = chunk.get(
                "document_id"
            )

            if document_id:

                document_ids.add(
                    document_id
                )


            # ----------------------------------------------
            # Check text
            # ----------------------------------------------

            text = chunk.get(
                "text",
                ""
            ).strip()

            if not text:

                empty_chunks += 1

                errors.append(
                    f"{chunk_file.name}: "
                    f"Empty chunk text"
                )

            else:

                word_counts.append(
                    len(text.split())
                )


        except Exception as e:

            errors.append(
                f"{chunk_file.name}: "
                f"Invalid JSON or read error: {e}"
            )


    # ========================================================
    # RESULTS
    # ========================================================

    print("\n" + "=" * 70)
    print("PUBLIC PDF CHUNK VALIDATION RESULT")
    print("=" * 70)

    print(
        f"Total chunk files: "
        f"{len(chunk_files)}"
    )

    print(
        f"Unique chunk IDs: "
        f"{len(chunk_ids)}"
    )

    print(
        f"Unique document IDs: "
        f"{len(document_ids)}"
    )

    print(
        f"Empty chunks: "
        f"{empty_chunks}"
    )

    print(
        f"Missing metadata fields: "
        f"{missing_metadata}"
    )


    if word_counts:

        print(
            f"Minimum chunk words: "
            f"{min(word_counts)}"
        )

        print(
            f"Maximum chunk words: "
            f"{max(word_counts)}"
        )

        print(
            f"Average chunk words: "
            f"{sum(word_counts) / len(word_counts):.2f}"
        )


    print("\n" + "-" * 70)

    if errors:

        print("VALIDATION RESULT: FAILED")

        print(
            f"\nErrors found: "
            f"{len(errors)}"
        )

        print("\nFirst 20 errors:")

        for error in errors[:20]:

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