import json
from pathlib import Path


class MetadataLoader:
    """
    Loads document metadata from the NovaTel document manifest
    and indexes it by document path and document ID.
    """

    def __init__(self, manifest_path):
        self.manifest_path = Path(manifest_path)
        self.documents = []
        self.by_path = {}
        self.by_id = {}

        self._load_manifest()
        self._build_indexes()

    def _load_manifest(self):
        if not self.manifest_path.exists():
            raise FileNotFoundError(
                f"Manifest not found: {self.manifest_path}"
            )

        with open(
            self.manifest_path,
            "r",
            encoding="utf-8"
        ) as f:
            self.documents = json.load(f)

        if not isinstance(self.documents, list):
            raise ValueError(
                "document_manifest.json must contain a list."
            )

    def _build_indexes(self):
        for document in self.documents:

            document_id = document.get("document_id")
            path = document.get("path")

            if not document_id:
                raise ValueError(
                    "Manifest entry missing document_id."
                )

            if not path:
                raise ValueError(
                    f"Manifest entry {document_id} "
                    "missing path."
                )

            if document_id in self.by_id:
                raise ValueError(
                    f"Duplicate document_id: {document_id}"
                )

            if path in self.by_path:
                raise ValueError(
                    f"Duplicate document path: {path}"
                )

            self.by_id[document_id] = document
            self.by_path[path] = document

    def get_by_path(self, path):
        """
        Return metadata for a document using its manifest path.
        """

        normalized = Path(path).as_posix()

        return self.by_path.get(normalized)

    def get_by_id(self, document_id):
        """
        Return metadata using document ID.
        """

        return self.by_id.get(document_id)

    def count(self):
        return len(self.documents)


if __name__ == "__main__":

    loader = MetadataLoader(
        "data/document_manifest.json"
    )

    print("=" * 60)
    print("NOVATEL METADATA LOADER TEST")
    print("=" * 60)

    print("Manifest documents:", loader.count())

    test_id = "FAQ_C01_001"

    metadata = loader.get_by_id(test_id)

    if metadata:
        print("\nTest document:")
        print("Document ID:", metadata["document_id"])
        print("Title:", metadata["title"])
        print("Type:", metadata["type"])
        print("Category:", metadata["category"])
        print("Department:", metadata["department"])
        print("Path:", metadata["path"])
    else:
        print(f"Document {test_id} not found.")