import json
from collections import defaultdict

MANIFEST_PATH = "data/document_manifest.json"


def main():

    with open(
        MANIFEST_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        manifest = json.load(f)

    categories = defaultdict(list)

    for item in manifest:
        categories[item["category"]].append(item)

    print("=" * 70)
    print("NOVATEL CATEGORY SUMMARY")
    print("=" * 70)

    for category in sorted(categories):

        documents = categories[category]

        print()
        print(f"{category} | {len(documents)} documents")

        for doc in documents[:5]:

            print(
                f"  - {doc['document_id']} | "
                f"{doc['title']}"
            )


if __name__ == "__main__":
    main()