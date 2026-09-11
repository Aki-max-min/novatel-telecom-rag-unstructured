import json
from pathlib import Path

from ingestion.document_schema import CanonicalDocument
from ingestion.chunker import DocumentChunker


# ============================================================
# PATH CONFIGURATION
# ============================================================

INPUT_DIR = Path(
    "data/processed/documents/public_pdfs"
)

OUTPUT_DIR = Path(
    "data/experiments/public_pdfs/chunks"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# LOAD CANONICAL DOCUMENT
# ============================================================

def load_document(document_path: Path) -> CanonicalDocument:
    """
    Load a processed JSON document and reconstruct
    it as a CanonicalDocument object.
    """

    with open(
        document_path,
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
        content=data.get(
            "content",
            ""
        ),
        file_path=data.get(
            "file_path",
            ""
        ),
        file_type=data.get(
            "file_type",
            ""
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("NOVATEL PUBLIC PDF DOCUMENT CHUNKING")
    print("=" * 70)

    # --------------------------------------------------------
    # FIND DOCUMENTS
    # --------------------------------------------------------

    document_files = sorted(
        INPUT_DIR.glob("*.json")
    )

    print(
        f"\nInput documents: "
        f"{len(document_files)}"
    )

    if not document_files:

        print(
            "\nERROR: No processed documents found."
        )

        return


    # --------------------------------------------------------
    # CREATE CHUNKER
    # --------------------------------------------------------

    chunker = DocumentChunker(
        max_words=250,
        overlap_words=40
    )


    total_chunks = 0
    failed_documents = 0
    chunks_per_document = []


    # ========================================================
    # PROCESS DOCUMENTS
    # ========================================================

    for index, document_path in enumerate(
        document_files,
        start=1
    ):

        print("\n" + "-" * 70)

        print(
            f"[{index}/{len(document_files)}] "
            f"Processing: {document_path.name}"
        )

        try:

            # ------------------------------------------------
            # LOAD DOCUMENT
            # ------------------------------------------------

            document = load_document(
                document_path
            )


            # ------------------------------------------------
            # CHUNK DOCUMENT
            # ------------------------------------------------

            chunks = chunker.chunk_document(
                document
            )


            # ------------------------------------------------
            # SAVE CHUNKS
            # ------------------------------------------------

            for chunk in chunks:

                output_path = (
                    OUTPUT_DIR /
                    f"{chunk.chunk_id}.json"
                )

                with open(
                    output_path,
                    "w",
                    encoding="utf-8"
                ) as f:

                    json.dump(
                        chunk.to_dict(),
                        f,
                        indent=2,
                        ensure_ascii=False
                    )


            document_chunk_count = len(chunks)

            total_chunks += document_chunk_count

            chunks_per_document.append(
                document_chunk_count
            )


            print(
                f"Words: "
                f"{len(document.content.split())}"
            )

            print(
                f"Chunks created: "
                f"{document_chunk_count}"
            )


        except Exception as e:

            print(
                f"ERROR processing "
                f"{document_path.name}"
            )

            print(
                f"Reason: {e}"
            )

            failed_documents += 1


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print("PUBLIC PDF CHUNKING RESULT")
    print("=" * 70)

    successful_documents = (
        len(document_files)
        - failed_documents
    )

    print(
        f"Documents processed: "
        f"{successful_documents}"
    )

    print(
        f"Total chunks: "
        f"{total_chunks}"
    )

    print(
        f"Failed documents: "
        f"{failed_documents}"
    )


    if chunks_per_document:

        print(
            f"Minimum chunks/document: "
            f"{min(chunks_per_document)}"
        )

        print(
            f"Maximum chunks/document: "
            f"{max(chunks_per_document)}"
        )

        average_chunks = (
            total_chunks /
            len(chunks_per_document)
        )

        print(
            f"Average chunks/document: "
            f"{average_chunks:.2f}"
        )


    print(
        f"\nChunks saved to: "
        f"{OUTPUT_DIR}"
    )


if __name__ == "__main__":
    main()