from dataclasses import dataclass, field
from typing import Any


@dataclass
class CanonicalDocument:
    document_id: str
    title: str
    document_type: str
    category: str
    department: str
    customer_scope: str
    version: str
    last_updated: str
    source_authority: str
    related_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    content: str = ""
    file_path: str = ""
    file_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
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
            "content": self.content,
            "file_path": self.file_path,
            "file_type": self.file_type,
        }