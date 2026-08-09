import json
from pathlib import Path

from ingestion.document_builder import DocumentBuilder
from ingestion.text_cleaner import TextCleaner


RAW_DIR = Path("data/raw/unstructured")
OUTPUT_DIR = Path("data/processed/documents")
MANIFEST_PATH = "data/document_manifest.json"


def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    builder = DocumentBuilder(
        MANIFEST_PATH
    )

    files = [
        path
        for path in RAW_DIR.rglob("*")
        if path.is_file()
    ]

    print("=" * 70)
    print("NOVATEL DOCUMENT PROCESSING")
    print("=" * 70)

    print(f"Input documents: {len(files)}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()

    successful = []
    failed = []

    for file_path in files:

        try:

            # Build canonical document
            document = builder.build(
                file_path
            )

            # Clean text
            document.content = TextCleaner.clean(
                document.content
            )

            # Validate content
            if not document.content.strip():

                raise ValueError(
                    "Cleaned document content is empty."
                )

            # Convert to dictionary
            output = document.to_dict()

            # Output filename
            output_file = (
                OUTPUT_DIR
                / f"{document.document_id}.json"
            )

            # Save processed document
            with open(
                output_file,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    output,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            successful.append(
                document.document_id
            )

        except Exception as e:

            failed.append(
                {
                    "file": str(file_path),
                    "error": str(e)
                }
            )

    print("-" * 70)
    print("PROCESSING RESULT")
    print("-" * 70)

    print(
        f"Successful: {len(successful)}"
    )

    print(
        f"Failed:     {len(failed)}"
    )

    print()

    if failed:

        print("=" * 70)
        print("FAILED DOCUMENTS")
        print("=" * 70)

        for item in failed:

            print(
                f"\nFile: {item['file']}"
            )

            print(
                f"Error: {item['error']}"
            )

    else:

        print("=" * 70)
        print("ALL DOCUMENTS PROCESSED SUCCESSFULLY")
        print("=" * 70)

        print(
            f"Processed files saved to: {OUTPUT_DIR}"
        )


if __name__ == "__main__":
    main()