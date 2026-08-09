from pathlib import Path
from document_loader import load_document


DATA_DIR = Path("data/raw/unstructured")


def main():
    files = [
        path
        for path in DATA_DIR.rglob("*")
        if path.is_file()
    ]

    print("=" * 60)
    print("NOVA TEL DOCUMENT LOADER — FULL DATASET TEST")
    print("=" * 60)

    print(f"Total files discovered: {len(files)}")
    print()

    successful = []
    failed = []

    for file_path in files:

        try:
            document = load_document(file_path)

            content = document["content"]

            if content is None:
                raise ValueError("Content is None")

            if isinstance(content, str):
                content_length = len(content)
            else:
                content_length = len(str(content))

            if content_length == 0:
                raise ValueError("Extracted content is empty")

            successful.append(
                {
                    "file": str(file_path),
                    "type": document["file_type"],
                    "characters": content_length
                }
            )

        except Exception as e:

            failed.append(
                {
                    "file": str(file_path),
                    "error": str(e)
                }
            )

    print("-" * 60)
    print("RESULT")
    print("-" * 60)

    print(f"Successful: {len(successful)}")
    print(f"Failed:     {len(failed)}")
    print()

    if successful:
        print("Files by type:")

        type_counts = {}

        for item in successful:
            file_type = item["type"]
            type_counts[file_type] = (
                type_counts.get(file_type, 0) + 1
            )

        for file_type, count in sorted(type_counts.items()):
            print(f"  {file_type}: {count}")

    print()

    if failed:

        print("=" * 60)
        print("FAILED FILES")
        print("=" * 60)

        for item in failed:
            print(f"\nFile: {item['file']}")
            print(f"Error: {item['error']}")

    else:

        print("=" * 60)
        print("ALL DOCUMENTS LOADED SUCCESSFULLY")
        print("=" * 60)


if __name__ == "__main__":
    main()