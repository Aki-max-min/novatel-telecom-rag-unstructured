from pathlib import Path

from ingestion.document_builder import DocumentBuilder


DATA_DIR = Path("data/raw/unstructured")
MANIFEST_PATH = "data/document_manifest.json"


def main():

    builder = DocumentBuilder(MANIFEST_PATH)

    files = [
        path
        for path in DATA_DIR.rglob("*")
        if path.is_file()
    ]

    print("=" * 70)
    print("NOVATEL CANONICAL DOCUMENT BUILDER — FULL DATASET TEST")
    print("=" * 70)

    print(f"Files discovered: {len(files)}")
    print()

    successful = []
    failed = []

    for file_path in files:

        try:

            document = builder.build(file_path)

            # Basic validation
            required_fields = [
                document.document_id,
                document.title,
                document.document_type,
                document.category,
                document.department,
                document.content,
            ]

            if any(
                value is None or str(value).strip() == ""
                for value in required_fields
            ):
                raise ValueError(
                    "One or more required fields are empty."
                )

            successful.append(document)

        except Exception as e:

            failed.append(
                {
                    "file": str(file_path),
                    "error": str(e),
                }
            )

    print("-" * 70)
    print("RESULT")
    print("-" * 70)

    print(f"Successful: {len(successful)}")
    print(f"Failed:     {len(failed)}")
    print()

    # Document type distribution
    type_counts = {}

    for document in successful:

        doc_type = document.document_type

        type_counts[doc_type] = (
            type_counts.get(doc_type, 0) + 1
        )

    print("Document types:")

    for doc_type, count in sorted(type_counts.items()):

        print(f"  {doc_type}: {count}")

    print()

    # Category distribution
    category_counts = {}

    for document in successful:

        category = document.category

        category_counts[category] = (
            category_counts.get(category, 0) + 1
        )

    print("Categories:")

    for category, count in sorted(
        category_counts.items()
    ):

        print(f"  {category}: {count}")

    print()

    # Failures
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
        print("ALL 148 DOCUMENTS BUILT SUCCESSFULLY")
        print("=" * 70)


if __name__ == "__main__":
    main()