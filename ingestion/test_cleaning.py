from ingestion.document_builder import DocumentBuilder
from ingestion.text_cleaner import TextCleaner


MANIFEST_PATH = "data/document_manifest.json"


def test_document(builder, file_path):
    document = builder.build(file_path)

    original = document.content
    cleaned = TextCleaner.clean(original)

    print("=" * 80)
    print(f"FILE: {file_path}")
    print("=" * 80)

    print("\n--- ORIGINAL ---\n")
    print(original[:1500])

    print("\n--- CLEANED ---\n")
    print(cleaned[:1500])

    print("\n--- STATS ---")
    print("Original characters:", len(original))
    print("Cleaned characters :", len(cleaned))
    print("Original lines     :", len(original.splitlines()))
    print("Cleaned lines      :", len(cleaned.splitlines()))


def main():

    builder = DocumentBuilder(MANIFEST_PATH)

    test_files = [
        "data/raw/unstructured/faq/FAQ_C01_001.json",
        "data/raw/unstructured/kb/KB_C02_plan_expiry.md",
        "data/raw/unstructured/sops/SOP_C03_RECHARGE_FAILURE.docx",
    ]

    for file_path in test_files:
        test_document(builder, file_path)


if __name__ == "__main__":
    main()