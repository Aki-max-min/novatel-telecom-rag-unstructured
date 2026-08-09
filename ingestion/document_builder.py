from pathlib import Path

from ingestion.document_loader import load_document
from ingestion.document_schema import CanonicalDocument
from ingestion.metadata_loader import MetadataLoader


class DocumentBuilder:
    """
    Combines:
    1. Raw document content
    2. Manifest metadata

    into one CanonicalDocument.
    """

    def __init__(self, manifest_path):
        self.metadata_loader = MetadataLoader(manifest_path)

    def build(self, file_path):
        file_path = Path(file_path)

        # Load raw content
        loaded = load_document(file_path)

        # Convert path to the same format used by the manifest
        manifest_path = file_path.as_posix()

        metadata = self.metadata_loader.get_by_path(manifest_path)

        if metadata is None:
            raise ValueError(
                f"No manifest metadata found for: {file_path}"
            )

        content = loaded["content"]

        # JSON FAQs are currently dictionaries.
        # Convert them to readable text for downstream processing.
        if isinstance(content, dict):
            content = self._json_to_text(content)

        elif isinstance(content, list):
            content = self._json_to_text(content)

        else:
            content = str(content)

        return CanonicalDocument(
            document_id=metadata["document_id"],
            title=metadata["title"],
            document_type=metadata["type"],
            category=metadata["category"],
            department=metadata["department"],
            customer_scope=metadata.get(
                "customer_scope",
                "unspecified"
            ),
            version=metadata.get(
                "version",
                "unspecified"
            ),
            last_updated=metadata.get(
                "last_updated",
                "unspecified"
            ),
            source_authority=metadata.get(
                "source_authority",
                "unspecified"
            ),
            related_ids=metadata.get(
                "related_ids",
                []
            ),
            tags=metadata.get(
                "tags",
                []
            ),
            content=content,
            file_path=str(file_path),
            file_type=loaded["file_type"],
        )

    @staticmethod
    def _json_to_text(data):
        """
        Convert structured JSON into semantic text suitable
        for downstream cleaning, chunking and embedding.

        Metadata such as category, department, version,
        tags and source authority is intentionally excluded
        because it is already stored separately on the
        CanonicalDocument.
        """

        if isinstance(data, dict):

            # FAQ-specific representation
            if "question" in data and "answer" in data:

                sections = []

                sections.append(
                    f"Question: {data['question']}"
                )

                sections.append(
                    f"Answer: {data['answer']}"
                )

                # category_name is semantic taxonomy information
                # and can be useful to retrieval, so retain it.
                if data.get("category_name"):
                    sections.append(
                        f"Topic: {data['category_name']}"
                    )

                return "\n\n".join(sections)

            # Generic JSON fallback
            sections = []

            metadata_fields = {
                "faq_id",
                "document_id",
                "category",
                "category_name",
                "department",
                "customer_scope",
                "last_updated",
                "version",
                "source_authority",
                "related_ids",
                "tags",
            }

            for key, value in data.items():

                if key in metadata_fields:
                    continue

                if isinstance(value, list):
                    value = ", ".join(
                        str(item)
                        for item in value
                    )

                sections.append(
                    f"{key}: {value}"
                )

            return "\n".join(sections)

        if isinstance(data, list):

            return "\n".join(
                str(item)
                for item in data
            )

        return str(data)


if __name__ == "__main__":

    builder = DocumentBuilder(
        "data/document_manifest.json"
    )

    test_file = (
        "data/raw/unstructured/faq/FAQ_C01_001.json"
    )

    document = builder.build(test_file)

    print("=" * 60)
    print("CANONICAL DOCUMENT BUILDER TEST")
    print("=" * 60)

    print("Document ID:", document.document_id)
    print("Title:", document.title)
    print("Type:", document.document_type)
    print("Category:", document.category)
    print("Department:", document.department)
    print("Customer Scope:", document.customer_scope)
    print("Version:", document.version)
    print("Source:", document.source_authority)
    print("File Type:", document.file_type)

    print("\nContent:")
    print(document.content[:1000])