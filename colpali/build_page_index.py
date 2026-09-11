from pathlib import Path
import json
import gc

import torch
import pymupdf

from page_renderer import render_pdf_page
from embedder import ColPaliEmbedder


# ============================================================
# PATHS
# ============================================================

PDF_ROOT = Path("data/raw/real_world/public_pdfs")

OUTPUT_ROOT = Path(
    "data/experiments/public_pdfs/colpali"
)

IMAGE_ROOT = OUTPUT_ROOT / "page_images"
EMBEDDING_ROOT = OUTPUT_ROOT / "embeddings"
METADATA_ROOT = OUTPUT_ROOT / "metadata"


# ============================================================
# SETTINGS
# ============================================================

DPI = 150


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("COLPALI PAGE INDEXING")
    print("=" * 70)

    # --------------------------------------------------------
    # Create output directories
    # --------------------------------------------------------

    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    EMBEDDING_ROOT.mkdir(parents=True, exist_ok=True)
    METADATA_ROOT.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # Find all PDFs recursively
    # --------------------------------------------------------

    pdf_files = sorted(PDF_ROOT.rglob("*.pdf"))

    print(f"\nPDFs found: {len(pdf_files)}")

    if len(pdf_files) != 10:
        print(
            f"WARNING: Expected 10 PDFs, found {len(pdf_files)}"
        )

    if not pdf_files:
        raise FileNotFoundError(
            f"No PDFs found inside {PDF_ROOT}"
        )

    # --------------------------------------------------------
    # Calculate total pages
    # --------------------------------------------------------

    pdf_page_counts = {}

    total_pages = 0

    for pdf_path in pdf_files:

        document = pymupdf.open(pdf_path)
        page_count = len(document)
        document.close()

        pdf_page_counts[pdf_path] = page_count
        
        total_pages += page_count

    print(f"Total pages: {total_pages}")

    # --------------------------------------------------------
    # Load ColPali
    # --------------------------------------------------------

    print("\nLoading ColPali...")

    embedder = ColPaliEmbedder()

    print("ColPali ready.")

    # --------------------------------------------------------
    # Process every PDF
    # --------------------------------------------------------

    processed_pages = 0
    skipped_pages = 0

    for pdf_path in pdf_files:

        relative_pdf = pdf_path.relative_to(PDF_ROOT)
        pdf_stem = pdf_path.stem

        page_count = pdf_page_counts[pdf_path]

        print("\n" + "=" * 70)
        print(f"PDF: {relative_pdf}")
        print(f"Pages: {page_count}")
        print("=" * 70)

        # ----------------------------------------------------
        # Create folders for this PDF
        # ----------------------------------------------------

        image_dir = IMAGE_ROOT / pdf_stem
        embedding_dir = EMBEDDING_ROOT / pdf_stem

        image_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        embedding_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        # ----------------------------------------------------
        # Process pages
        # ----------------------------------------------------

        
        
        for page_number in range(page_count):

            page_id = processed_pages + skipped_pages

            page_number_display = page_number + 1

            embedding_path = (
                embedding_dir /
                f"page_{page_number_display:04d}.pt"
            )

            image_path = (
                image_dir /
                f"page_{page_number_display:04d}.jpg"
            )

            # ------------------------------------------------
            # Resume support
            # ------------------------------------------------

            if embedding_path.exists():

                print(
                    f"[SKIP] Page {page_number_display}/{page_count} "
                    f"(embedding already exists)"
                )

                skipped_pages += 1

                continue

            # ------------------------------------------------
            # Progress
            # ------------------------------------------------

            current_page = (
                processed_pages +
                skipped_pages +
                1
            )

            print(
                f"\n[PROCESS] "
                f"{current_page}/{total_pages} | "
                f"{pdf_stem} | "
                f"Page {page_number_display}/{page_count}"
            )

            # ------------------------------------------------
            # Render PDF page
            # ------------------------------------------------

            image = render_pdf_page(
                pdf_path,
                page_number=page_number,
                dpi=DPI
            )

            print(
                f"  Image size: {image.size}"
            )

            # ------------------------------------------------
            # Save page image
            # ------------------------------------------------

            image.save(
                image_path,
                format="JPEG",
                quality=90
            )

            # ------------------------------------------------
            # Generate ColPali representation
            # ------------------------------------------------

            print("  Generating ColPali representation...")

            embedding = embedder.embed_image(image)

            # ------------------------------------------------
            # Move embedding to CPU
            # ------------------------------------------------

            embedding_cpu = (
                embedding
                .detach()
                .cpu()
            )

            print(
                f"  Embedding shape: "
                f"{tuple(embedding_cpu.shape)}"
            )

            # ------------------------------------------------
            # Save embedding immediately
            # ------------------------------------------------

            torch.save(
                embedding_cpu,
                embedding_path
            )

            print(
                f"  Saved embedding: "
                f"{embedding_path}"
            )

            # ------------------------------------------------
            # Save metadata for this page
            # ------------------------------------------------

            metadata = {
                "page_id": current_page - 1,
                "pdf_path": str(relative_pdf),
                "pdf_name": pdf_path.name,
                "document_id": pdf_stem,
                "page_number": page_number_display,
                "page_number_zero_based": page_number,
                "image_path": str(
                    image_path.relative_to(OUTPUT_ROOT)
                ),
                "embedding_path": str(
                    embedding_path.relative_to(OUTPUT_ROOT)
                ),
                "embedding_shape": list(
                    embedding_cpu.shape
                ),
            }

            metadata_path = (
                METADATA_ROOT /
                f"{pdf_stem}_page_{page_number_display:04d}.json"
            )

            with open(
                metadata_path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    metadata,
                    f,
                    indent=2,
                    ensure_ascii=False
                )

            # ------------------------------------------------
            # Free memory
            # ------------------------------------------------

            del image
            del embedding
            del embedding_cpu

            gc.collect()

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            processed_pages += 1

            # ------------------------------------------------
            # Show GPU memory
            # ------------------------------------------------

            if torch.cuda.is_available():

                allocated = (
                    torch.cuda.memory_allocated()
                    / (1024 ** 2)
                )

                reserved = (
                    torch.cuda.memory_reserved()
                    / (1024 ** 2)
                )

                print(
                    f"  GPU memory: "
                    f"{allocated:.0f} MB allocated, "
                    f"{reserved:.0f} MB reserved"
                )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print("COLPALI PAGE INDEXING COMPLETE")
    print("=" * 70)

    print(f"\nTotal PDFs:       {len(pdf_files)}")
    print(f"Total pages:      {total_pages}")
    print(f"Processed pages:  {processed_pages}")
    print(f"Skipped pages:    {skipped_pages}")

    print("\nOutput directory:")
    print(OUTPUT_ROOT)

    print("\nPage images:")
    print(IMAGE_ROOT)

    print("\nEmbeddings:")
    print(EMBEDDING_ROOT)

    print("\nMetadata:")
    print(METADATA_ROOT)

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()