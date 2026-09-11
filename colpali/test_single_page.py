from pathlib import Path
import torch

from page_renderer import render_pdf_page
from embedder import ColPaliEmbedder


# --------------------------------------------------
# Find the existing TRAI PDF recursively
# --------------------------------------------------

PDF_ROOT = Path("data/raw/real_world/public_pdfs")

PDF_MATCHES = list(
    PDF_ROOT.rglob("01_telecom_consumers_protection*.pdf")
)

if not PDF_MATCHES:
    raise FileNotFoundError(
        f"Could not find the telecom consumers protection PDF "
        f"inside: {PDF_ROOT}"
    )

PDF_PATH = PDF_MATCHES[0]


def main():

    print("=" * 60)
    print("COLPALI SINGLE PAGE TEST")
    print("=" * 60)

    # --------------------------------------------------
    # 1. Show the PDF being used
    # --------------------------------------------------

    print("\nPDF found:")
    print(PDF_PATH)

    # --------------------------------------------------
    # 2. Check GPU
    # --------------------------------------------------

    print("\nChecking GPU...")

    if torch.cuda.is_available():
        print("CUDA available: True")
        print("GPU:", torch.cuda.get_device_name(0))
    else:
        print("CUDA available: False")
        print("WARNING: ColPali will run on CPU.")

    # --------------------------------------------------
    # 3. Render first PDF page
    # --------------------------------------------------

    print("\nRendering PDF page...")

    image = render_pdf_page(
        PDF_PATH,
        page_number=0,
        dpi=150
    )

    print("Page rendered successfully.")
    print("Image size:", image.size)

    # --------------------------------------------------
    # 4. Load ColPali
    # --------------------------------------------------

    print("\nLoading ColPali...")

    embedder = ColPaliEmbedder()

    # --------------------------------------------------
    # 5. Generate ColPali representation
    # --------------------------------------------------

    print("\nGenerating ColPali page representation...")

    embedding = embedder.embed_image(image)

    print("Embedding generated successfully.")

    # --------------------------------------------------
    # 6. Display embedding information
    # --------------------------------------------------

    print("\nEmbedding information:")
    print("Shape:", embedding.shape)
    print("Device:", embedding.device)
    print("Dtype:", embedding.dtype)

    # --------------------------------------------------
    # 7. Final result
    # --------------------------------------------------

    print("\n" + "=" * 60)
    print("TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()