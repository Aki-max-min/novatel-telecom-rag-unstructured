import json
from pathlib import Path

from ingestion.document_schema import CanonicalDocument
from ingestion.chunker import DocumentChunker


INPUT_DIR = Path(
    "data/processed/documents"
)

OUTPUT_DIR = Path(
    "data/processed/chunks"
)


def load_canonical_document(
    file_path
):
    """
    Load a processed JSON document and
    reconstruct a CanonicalDocument.
    """

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    return CanonicalDocument(
        document_id=data["document_id"],
        title=data["title"],
        document_type=data["document_type"],
        category=data["category"],
        department=data["department"],
        customer_scope=data["customer_scope"],
        version=data["version"],
        last_updated=data["last_updated"],
        source_authority=data["source_authority"],
        related_ids=data.get(
            "related_ids",
            []
        ),
        tags=data.get(
            "tags",
            []
        ),
        content=data["content"],
        file_path=data.get(
            "file_path",
            ""
        ),
        file_type=data.get(
            "file_type",
            ""
        ),
    )


def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    files = sorted(
        INPUT_DIR.glob("*.json")
    )

    print("=" * 70)
    print("NOVATEL BATCH DOCUMENT CHUNKING")
    print("=" * 70)

    print(
        "Input documents:",
        len(files)
    )

    chunker = DocumentChunker(
        max_words=450,
        overlap_words=60
    )

    total_chunks = 0
    failed = 0

    chunk_counts = []

    for file_path in files:

        try:

            document = (
                load_canonical_document(
                    file_path
                )
            )

            chunks = (
                chunker.chunk_document(
                    document
                )
            )

            chunk_counts.append(
                len(chunks)
            )

            for chunk in chunks:

                output_file = (
                    OUTPUT_DIR
                    / f"{chunk.chunk_id}.json"
                )

                with open(
                    output_file,
                    "w",
                    encoding="utf-8"
                ) as f:

                    json.dump(
                        chunk.to_dict(),
                        f,
                        indent=2,
                        ensure_ascii=False
                    )

                total_chunks += 1

        except Exception as e:

            failed += 1

            print(
                f"FAILED: {file_path}"
            )

            print(
                f"Reason: {e}"
            )

    print()
    print("=" * 70)
    print("CHUNKING RESULT")
    print("=" * 70)

    print(
        "Documents processed:",
        len(files)
    )

    print(
        "Total chunks:",
        total_chunks
    )

    print(
        "Failed documents:",
        failed
    )

    if chunk_counts:

        print(
            "Minimum chunks/document:",
            min(chunk_counts)
        )

        print(
            "Maximum chunks/document:",
            max(chunk_counts)
        )

        print(
            "Average chunks/document:",
            round(
                sum(chunk_counts)
                / len(chunk_counts),
                2
            )
        )


if __name__ == "__main__":
    main()