from pathlib import Path
import pymupdf


PDF_ROOT = Path("data/raw/real_world/public_pdfs")


def main():
    print("=" * 60)
    print("TRAI PDF PAGE COUNT")
    print("=" * 60)

    pdf_files = sorted(PDF_ROOT.rglob("*.pdf"))

    print(f"\nPDFs found: {len(pdf_files)}")

    total_pages = 0

    for pdf_path in pdf_files:
        document = pymupdf.open(pdf_path)
        page_count = len(document)
        document.close()

        relative_path = pdf_path.relative_to(PDF_ROOT)

        print(f"{relative_path} -> {page_count} pages")

        total_pages += page_count

    print("\n" + "-" * 60)
    print(f"TOTAL PDFs:  {len(pdf_files)}")
    print(f"TOTAL PAGES: {total_pages}")
    print("=" * 60)


if __name__ == "__main__":
    main()