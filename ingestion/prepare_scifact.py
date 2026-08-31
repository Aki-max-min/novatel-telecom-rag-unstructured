import json
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_FILE = Path(
    "data/raw/real_world/scifact/scifact/corpus.jsonl"
)

OUTPUT_DIR = Path(
    "data/processed/documents/scifact"
)

# Number of SciFact documents to use for the first experiment
MAX_DOCUMENTS = 100


# ============================================================
# MAIN FUNCTION
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    total = 0

    print("=" * 70)
    print("PREPARING SCIFACT DOCUMENTS")
    print("=" * 70)

    print("Maximum documents:", MAX_DOCUMENTS)
    print("Input file:", INPUT_FILE)

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        for line in f:

            # Stop after processing MAX_DOCUMENTS
            if total >= MAX_DOCUMENTS:
                break

            # Skip empty lines
            if not line.strip():
                continue

            raw_doc = json.loads(line)

            document_id = (
                "SCIFACT_"
                + str(raw_doc["_id"])
            )

            document = {

                "document_id": document_id,

                "title": raw_doc.get(
                    "title",
                    ""
                ),

                "document_type": (
                    "Scientific Literature"
                ),

                "content": raw_doc.get(
                    "text",
                    ""
                ),

                "category": "SCIFACT",

                "category_name": (
                    "Scientific Literature"
                ),

                "department": (
                    "Research Dataset"
                ),

                "customer_scope": "public",

                "last_updated": "2026-08-31",

                "version": "1.0",

                "source_authority": (
                    "BEIR SciFact"
                ),

                "related_ids": [],

                "tags": [
                    "scifact",
                    "scientific",
                    "research",
                    "real_world_data"
                ],

                "source_dataset": (
                    "BEIR/SciFact"
                ),

                "file_path": str(
                    INPUT_FILE
                ),

                "file_type": "jsonl"
            }

            output_file = (
                OUTPUT_DIR
                / f"{document_id}.json"
            )

            with open(
                output_file,
                "w",
                encoding="utf-8"
            ) as out:

                json.dump(
                    document,
                    out,
                    indent=2,
                    ensure_ascii=False
                )

            total += 1

            # Progress message
            if total % 10 == 0:
                print(
                    f"Processed {total}/{MAX_DOCUMENTS} documents"
                )

    print()
    print("=" * 70)
    print("SCIFACT PREPARATION COMPLETE")
    print("=" * 70)
    print("Documents created:", total)
    print("Output directory:", OUTPUT_DIR)


if __name__ == "__main__":
    main()