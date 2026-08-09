import json
from pathlib import Path


PROCESSED_DIR = Path("data/processed/documents")


def main():

    files = list(
        PROCESSED_DIR.glob("*.json")
    )

    print("=" * 70)
    print("NOVATEL PROCESSED DOCUMENT ANALYSIS")
    print("=" * 70)

    print(f"Documents: {len(files)}")
    print()

    documents = []

    for file_path in files:

        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:

            document = json.load(f)

        content = document.get(
            "content",
            ""
        )

        documents.append(
            {
                "id": document["document_id"],
                "type": document["document_type"],
                "category": document["category"],
                "characters": len(content),
                "words": len(content.split()),
            }
        )

    # Overall statistics
    character_counts = [
        d["characters"]
        for d in documents
    ]

    word_counts = [
        d["words"]
        for d in documents
    ]

    print("Overall statistics")
    print("-" * 70)

    print(
        "Minimum characters:",
        min(character_counts)
    )

    print(
        "Maximum characters:",
        max(character_counts)
    )

    print(
        "Average characters:",
        round(
            sum(character_counts)
            / len(character_counts),
            2
        )
    )

    print(
        "Minimum words:",
        min(word_counts)
    )

    print(
        "Maximum words:",
        max(word_counts)
    )

    print(
        "Average words:",
        round(
            sum(word_counts)
            / len(word_counts),
            2
        )
    )

    print()

    # Statistics by document type
    print("Statistics by document type")
    print("-" * 70)

    types = {}

    for document in documents:

        doc_type = document["type"]

        types.setdefault(
            doc_type,
            []
        ).append(
            document
        )

    for doc_type in sorted(types):

        docs = types[doc_type]

        words = [
            d["words"]
            for d in docs
        ]

        print(
            f"{doc_type}: "
            f"{len(docs)} documents | "
            f"min={min(words)} words | "
            f"max={max(words)} words | "
            f"avg={round(sum(words)/len(words), 1)} words"
        )

    print()

    # Longest documents
    print("10 longest documents")
    print("-" * 70)

    longest = sorted(
        documents,
        key=lambda x: x["words"],
        reverse=True
    )[:10]

    for document in longest:

        print(
            f"{document['id']} | "
            f"{document['type']} | "
            f"{document['words']} words"
        )


if __name__ == "__main__":
    main()