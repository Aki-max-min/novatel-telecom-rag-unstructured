import json
import re
from pathlib import Path

import fitz

from ingestion.document_schema import CanonicalDocument


# ============================================================
# PATH CONFIGURATION
# ============================================================

INPUT_DIR = Path("data/raw/real_world/public_pdfs")
OUTPUT_DIR = Path("data/processed/documents/public_pdfs")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_text(text: str) -> str:
    """
    Clean extracted PDF text while preserving paragraph structure.
    """

    # Replace multiple spaces and tabs with one space
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove spaces before punctuation
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)

    return text.strip()


# ============================================================
# HINDI / DEVANAGARI FILTERING
# ============================================================

def remove_devanagari_lines(text: str) -> str:
    """
    Remove lines dominated by Devanagari characters.

    This is useful for bilingual TRAI documents.
    """

    cleaned_lines = []

    for line in text.splitlines():

        line = line.strip()

        if not line:
            cleaned_lines.append("")
            continue

        devanagari_chars = len(
            re.findall(r"[\u0900-\u097F]", line)
        )

        total_alpha_chars = len(
            re.findall(r"[A-Za-z\u0900-\u097F]", line)
        )

        if total_alpha_chars > 0:

            ratio = devanagari_chars / total_alpha_chars

            # Skip lines dominated by Hindi/Devanagari
            if ratio > 0.30:
                continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


# ============================================================
# PDF TEXT EXTRACTION
# ============================================================

def extract_pdf_text(pdf_path: Path):
    """
    Extract text from all pages of a PDF.

    Returns:
        full_text
        page_count
    """

    document = fitz.open(pdf_path)

    pages_text = []

    for page in document:

        page_text = page.get_text("text")

        if page_text:
            pages_text.append(page_text)

    page_count = len(document)

    document.close()

    full_text = "\n\n".join(pages_text)

    return full_text, page_count


# ============================================================
# DOCUMENT ID GENERATION
# ============================================================

def generate_document_id(pdf_path: Path) -> str:
    """
    Generate a stable document ID from filename.

    Example:
    01_telecom_consumers_protection.pdf

    becomes:
    PUBLIC_PDF_01_TELECOM_CONSUMERS_PROTECTION
    """

    stem = pdf_path.stem.upper()

    stem = re.sub(
        r"[^A-Z0-9]+",
        "_",
        stem
    )

    return f"PUBLIC_PDF_{stem}"


# ============================================================
# DOCUMENT TYPE DETECTION
# ============================================================

def get_document_type(pdf_path: Path) -> str:
    """
    Determine document type based on its folder.
    """

    parent_folder = pdf_path.parent.name.lower()

    mapping = {
        "regulations": "REGULATION",
        "reports": "REPORT",
        "consultation_documents": "CONSULTATION_DOCUMENT",
    }

    return mapping.get(
        parent_folder,
        "PUBLIC_DOCUMENT"
    )


# ============================================================
# MAIN PROCESSING
# ============================================================

def main():

    print("=" * 70)
    print("NOVATEL PUBLIC TELECOM PDF PREPARATION")
    print("=" * 70)

    # Check input directory
    if not INPUT_DIR.exists():

        print("\nERROR: Input directory not found:")
        print(INPUT_DIR)

        return

    # Find all PDFs recursively
    pdf_files = sorted(
        INPUT_DIR.rglob("*.pdf")
    )

    print(f"\nPDF files discovered: {len(pdf_files)}")

    if len(pdf_files) == 0:

        print("\nNo PDF files found.")

        return

    processed = 0
    failed = 0

    # ========================================================
    # PROCESS EACH PDF
    # ========================================================

    for index, pdf_path in enumerate(
        pdf_files,
        start=1
    ):

        print("\n" + "-" * 70)

        print(
            f"[{index}/{len(pdf_files)}] "
            f"Processing: {pdf_path.name}"
        )

        try:

            # ------------------------------------------------
            # Extract PDF text
            # ------------------------------------------------

            raw_text, page_count = extract_pdf_text(
                pdf_path
            )

            # ------------------------------------------------
            # Remove Hindi-heavy lines
            # ------------------------------------------------

            filtered_text = remove_devanagari_lines(
                raw_text
            )

            # ------------------------------------------------
            # Clean text
            # ------------------------------------------------

            cleaned_text = clean_text(
                filtered_text
            )

            # ------------------------------------------------
            # Validate extraction
            # ------------------------------------------------

            if len(cleaned_text) < 200:

                print(
                    "WARNING: Extracted text too short "
                    f"({len(cleaned_text)} characters). "
                    "Skipping."
                )

                failed += 1
                continue

            # ------------------------------------------------
            # Generate metadata
            # ------------------------------------------------

            document_id = generate_document_id(
                pdf_path
            )

            document_type = get_document_type(
                pdf_path
            )

            relative_path = str(
                pdf_path.relative_to(INPUT_DIR)
            ).replace("\\", "/")


            # ------------------------------------------------
            # CREATE CANONICAL DOCUMENT
            #
            # This exactly matches document_schema.py
            # ------------------------------------------------

            document = CanonicalDocument(
                document_id=document_id,

                title=pdf_path.stem.replace("_", " "),

                document_type=document_type,

                category="PUBLIC_TELECOM",

                department="Real World Telecom Data",

                customer_scope="public",

                version="1.0",

                last_updated="2026-08-31",

                source_authority="TRAI",

                related_ids=[],

                tags=[
                    "real_world_data",
                    "telecom",
                    "public_pdf",
                    document_type.lower()
                ],

                content=cleaned_text,

                file_path=relative_path,

                file_type="pdf"
            )


            # ------------------------------------------------
            # SAVE DOCUMENT
            # ------------------------------------------------

            output_path = (
                OUTPUT_DIR /
                f"{document_id}.json"
            )

            with open(
                output_path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    document.to_dict(),
                    f,
                    indent=2,
                    ensure_ascii=False
                )


            # ------------------------------------------------
            # PRINT RESULT
            # ------------------------------------------------

            print(f"Pages: {page_count}")

            print(
                f"Extracted characters: "
                f"{len(cleaned_text)}"
            )

            print(
                f"Document ID: {document_id}"
            )

            print(
                f"Document type: {document_type}"
            )

            print(
                f"Saved: {output_path}"
            )

            processed += 1


        except Exception as e:

            print(
                f"ERROR processing {pdf_path.name}"
            )

            print(
                f"Reason: {e}"
            )

            failed += 1


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print("PUBLIC PDF PREPARATION RESULT")
    print("=" * 70)

    print(
        f"PDF files discovered: {len(pdf_files)}"
    )

    print(
        f"Successfully processed: {processed}"
    )

    print(
        f"Failed: {failed}"
    )

    print(
        f"Output directory: {OUTPUT_DIR}"
    )


if __name__ == "__main__":
    main()