from pathlib import Path
import pymupdf


def render_pdf_page(pdf_path, page_number=0, dpi=150):
    """
    Render one PDF page as a PIL image.

    Args:
        pdf_path: Path to the PDF.
        page_number: Zero-based page number.
        dpi: Rendering resolution.

    Returns:
        PIL Image
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    document = pymupdf.open(pdf_path)

    if page_number < 0 or page_number >= len(document):
        document.close()
        raise ValueError(
            f"Invalid page number {page_number}. "
            f"PDF has {len(document)} pages."
        )

    page = document[page_number]

    zoom = dpi / 72
    matrix = pymupdf.Matrix(zoom, zoom)

    pixmap = page.get_pixmap(matrix=matrix, alpha=False)

    image = pixmap.pil_image()

    document.close()

    return image