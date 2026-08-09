import json
from pathlib import Path


CHUNK_DIR = Path(
    "data/processed/chunks"
)


REQUIRED_FIELDS = [
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
    "source_authority",
    "related_ids",
    "tags",
    "file_path",
    "file_type",
]


def main():

    files = sorted(
        CHUNK_DIR.glob("*.json")
    )

    print("=" * 70)
    print("NOVATEL CHUNK DATASET VALIDATION")
    print("=" * 70)

    print(
        "Chunk files discovered:",
        len(files)
    )

    errors = []

    chunk_ids = set()
    document_ids = set()

    for file_path in files:

        try:

            with open(
                file_path,
                "r",
                encoding="utf-8"
            ) as f:

                chunk = json.load(f)

        except Exception as e:

            errors.append(
                f"{file_path.name}: invalid JSON - {e}"
            )

            continue

        # Required fields
        for field in REQUIRED_FIELDS:

            if field not in chunk:

                errors.append(
                    f"{file_path.name}: "
                    f"missing field '{field}'"
                )

        # Empty text
        if not chunk.get("text", "").strip():

            errors.append(
                f"{file_path.name}: empty text"
            )

        # Duplicate chunk IDs
        chunk_id = chunk.get(
            "chunk_id"
        )

        if chunk_id in chunk_ids:

            errors.append(
                f"{file_path.name}: "
                f"duplicate chunk_id '{chunk_id}'"
            )

        chunk_ids.add(chunk_id)

        # Document IDs
        document_id = chunk.get(
            "document_id"
        )

        if document_id:
            document_ids.add(
                document_id
            )

        # Chunk index
        if chunk.get("chunk_index") != 0:

            errors.append(
                f"{file_path.name}: "
                f"unexpected chunk_index "
                f"{chunk.get('chunk_index')}"
            )

        # Category validation
        category = chunk.get(
            "category"
        )

        if category != "GENERAL":

            if not (
                isinstance(category, str)
                and category.startswith("C")
                and category[1:].isdigit()
            ):

                errors.append(
                    f"{file_path.name}: "
                    f"invalid category '{category}'"
                )

    print()

    print(
        "Unique chunk IDs:",
        len(chunk_ids)
    )

    print(
        "Unique document IDs:",
        len(document_ids)
    )

    print()

    if errors:

        print(
            "VALIDATION RESULT: FAILED"
        )

        print(
            "Errors:",
            len(errors)
        )

        print()

        for error in errors[:50]:

            print(
                "ERROR:",
                error
            )

        if len(errors) > 50:

            print(
                f"... and "
                f"{len(errors) - 50} more"
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