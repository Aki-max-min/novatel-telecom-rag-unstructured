from docx import Document


file_path = (
    "data/raw/unstructured/sops/"
    "SOP_C03_RECHARGE_FAILURE.docx"
)

document = Document(file_path)

print("=" * 70)
print("DOCX RUN INSPECTION")
print("=" * 70)

for i, paragraph in enumerate(document.paragraphs):

    if not paragraph.text.strip():
        continue

    print(f"\nPARAGRAPH {i}")
    print("-" * 70)

    print("FULL TEXT:")
    print(repr(paragraph.text))

    print("\nRUNS:")

    for j, run in enumerate(paragraph.runs):

        print(
            f"  Run {j}: {repr(run.text)}"
        )