from pathlib import Path
import json

from docx import Document
from pypdf import PdfReader
import zipfile
import xml.etree.ElementTree as ET


def load_json(file_path):
    """Load a JSON file and return its parsed content."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_markdown(file_path):
    """Load a Markdown file as plain text."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def load_docx(file_path):
    """
    Extract text directly from the DOCX XML.

    This preserves the exact text stored in the DOCX
    document.xml instead of relying on python-docx's
    paragraph reconstruction.

    Paragraph boundaries are preserved.
    """

    namespace = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    }

    paragraphs = []

    with zipfile.ZipFile(file_path, "r") as archive:

        xml_content = archive.read(
            "word/document.xml"
        )

    root = ET.fromstring(xml_content)

    for paragraph in root.findall(
        ".//w:body/w:p",
        namespace
    ):

        text_parts = []

        for text_node in paragraph.findall(
            ".//w:t",
            namespace
        ):

            if text_node.text:
                text_parts.append(
                    text_node.text
                )

        text = "".join(text_parts).strip()

        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)

def load_pdf(file_path):
    """Extract text from a PDF file."""
    reader = PdfReader(file_path)

    pages = []

    for page in reader.pages:
        text = page.extract_text()

        if text:
            pages.append(text.strip())

    return "\n\n".join(pages)


def load_document(file_path):
    """
    Load a document based on its file extension.

    Returns:
        dict containing:
        - file_path
        - file_name
        - file_type
        - content
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    extension = path.suffix.lower()

    if extension == ".json":
        content = load_json(path)
        file_type = "json"

    elif extension == ".md":
        content = load_markdown(path)
        file_type = "markdown"

    elif extension == ".docx":
        content = load_docx(path)
        file_type = "docx"

    elif extension == ".pdf":
        content = load_pdf(path)
        file_type = "pdf"

    else:
        raise ValueError(
            f"Unsupported file type: {extension}"
        )

    return {
        "file_path": str(path),
        "file_name": path.name,
        "file_type": file_type,
        "content": content
    }


if __name__ == "__main__":

    print("Document Loader Test")
    print("=" * 50)

    test_file = (
        "data/raw/unstructured/faq/FAQ_C01_001.json"
    )

    document = load_document(test_file)

    print("File:", document["file_name"])
    print("Type:", document["file_type"])
    print("Content type:", type(document["content"]).__name__)

    if isinstance(document["content"], dict):
        print(
            "JSON keys:",
            list(document["content"].keys())
        )

    else:
        print(
            "Content preview:",
            document["content"][:500]
        )