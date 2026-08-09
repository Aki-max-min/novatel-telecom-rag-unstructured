import json
import re
from pathlib import Path

from ingestion.document_builder import DocumentBuilder


MANIFEST_PATH = "data/document_manifest.json"

# Patterns that commonly indicate a missing space.
PATTERNS = [
    r"\b[A-Za-z]{3,}(?:Ops|SOP|Team|Dashboard)\b",
    r":(?=[A-Za-z])",
    r"\bto(?:the|a|an)\b",
    r"\bfrom(?:the|a|an)\b",
    r"\bby(?:the|a|an)\b",
    r"\bof(?:the|a|an)\b",
]


def main():

    manifest = json.load(
        open(
            MANIFEST_PATH,
            "r",
            encoding="utf-8"
        )
    )

    builder = DocumentBuilder(
        MANIFEST_PATH
    )

    suspicious = []

    for item in manifest:

        file_path = item["path"]

        try:

            document = builder.build(
                file_path
            )

            text = document.content

            matches = []

            for pattern in PATTERNS:

                found = re.findall(
                    pattern,
                    text,
                    flags=re.IGNORECASE
                )

                matches.extend(found)

            if matches:

                suspicious.append(
                    {
                        "id": document.document_id,
                        "type": document.document_type,
                        "matches": matches,
                    }
                )

        except Exception as e:

            print(
                f"ERROR: {file_path}: {e}"
            )

    print("=" * 70)
    print("NOVATEL SPACING DIAGNOSTIC")
    print("=" * 70)

    print(
        "Documents scanned:",
        len(manifest)
    )

    print(
        "Documents with suspicious patterns:",
        len(suspicious)
    )

    print()

    for item in suspicious:

        print(
            f"{item['id']} | "
            f"{item['type']} | "
            f"{item['matches']}"
        )


if __name__ == "__main__":
    main()