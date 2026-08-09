from dataclasses import dataclass, field


@dataclass
class DocumentChunk:
    """
    Represents one retrievable chunk from a document.
    """

    chunk_id: str
    document_id: str
    chunk_index: int
    text: str

    title: str
    document_type: str
    category: str
    department: str
    customer_scope: str

    version: str
    last_updated: str
    source_authority: str

    related_ids: list[str] = field(
        default_factory=list
    )

    tags: list[str] = field(
        default_factory=list
    )

    file_path: str = ""
    file_type: str = ""

    def to_dict(self):
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text,

            "title": self.title,
            "document_type": self.document_type,
            "category": self.category,
            "department": self.department,
            "customer_scope": self.customer_scope,

            "version": self.version,
            "last_updated": self.last_updated,
            "source_authority": self.source_authority,

            "related_ids": self.related_ids,
            "tags": self.tags,

            "file_path": self.file_path,
            "file_type": self.file_type,
        }


class DocumentChunker:
    """
    Structure-preserving chunker.

    Small documents remain intact as one chunk.

    Larger documents are split into overlapping
    word-based chunks.
    """

    def __init__(
        self,
        max_words=450,
        overlap_words=60
    ):

        self.max_words = max_words
        self.overlap_words = overlap_words

        if overlap_words >= max_words:
            raise ValueError(
                "overlap_words must be smaller "
                "than max_words."
            )

    def chunk_document(self, document):

        text = document.content.strip()

        if not text:
            return []

        words = text.split()

        # --------------------------------------------------
        # Small document:
        # Keep the entire semantic document together.
        # --------------------------------------------------

        if len(words) <= self.max_words:

            return [
                self._create_chunk(
                    document,
                    text,
                    0
                )
            ]

        # --------------------------------------------------
        # Larger document:
        # Split with overlap.
        # --------------------------------------------------

        chunks = []

        start = 0
        chunk_index = 0

        while start < len(words):

            end = min(
                start + self.max_words,
                len(words)
            )

            chunk_words = words[
                start:end
            ]

            chunk_text = " ".join(
                chunk_words
            )

            chunks.append(
                self._create_chunk(
                    document,
                    chunk_text,
                    chunk_index
                )
            )

            chunk_index += 1

            if end >= len(words):
                break

            start = (
                end - self.overlap_words
            )

        return chunks

    @staticmethod
    def _create_chunk(
        document,
        text,
        chunk_index
    ):

        chunk_id = (
            f"{document.document_id}"
            f"_chunk_{chunk_index:03d}"
        )

        return DocumentChunk(
            chunk_id=chunk_id,
            document_id=document.document_id,
            chunk_index=chunk_index,
            text=text,

            title=document.title,
            document_type=document.document_type,
            category=document.category,
            department=document.department,
            customer_scope=document.customer_scope,

            version=document.version,
            last_updated=document.last_updated,
            source_authority=document.source_authority,

            related_ids=document.related_ids.copy(),
            tags=document.tags.copy(),

            file_path=document.file_path,
            file_type=document.file_type,
        )


if __name__ == "__main__":

    from ingestion.document_builder import (
        DocumentBuilder
    )

    from ingestion.text_cleaner import (
        TextCleaner
    )

    builder = DocumentBuilder(
        "data/document_manifest.json"
    )

    document = builder.build(
        "data/raw/unstructured/sops/"
        "SOP_C03_RECHARGE_FAILURE.docx"
    )

    document.content = TextCleaner.clean(
        document.content
    )

    chunker = DocumentChunker()

    chunks = chunker.chunk_document(
        document
    )

    print("=" * 70)
    print("CHUNKER TEST")
    print("=" * 70)

    print(
        "Document:",
        document.document_id
    )

    print(
        "Word count:",
        len(document.content.split())
    )

    print(
        "Chunks:",
        len(chunks)
    )

    for chunk in chunks:

        print("\n" + "-" * 70)

        print(
            "Chunk ID:",
            chunk.chunk_id
        )

        print(
            "Chunk index:",
            chunk.chunk_index
        )

        print(
            "Words:",
            len(chunk.text.split())
        )

        print("\nText:\n")

        print(chunk.text)