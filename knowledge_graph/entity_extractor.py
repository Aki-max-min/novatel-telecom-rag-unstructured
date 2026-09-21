"""Deterministic node extraction for the NovaTel knowledge graph.

Reads the canonical documents in ``data/processed/documents/*.json`` and emits
one node per distinct entity key. Hub entities (Department, Category, Tag, ...)
are deduplicated, so ``Department::Network`` exists once no matter how many
documents point at it.

No NLP, no LLM, no ML: every node comes from reading a declared metadata field.
Running this twice over the same corpus produces identical output.

Run standalone to write ``knowledge_graph/output/nodes.json``::

    python -m knowledge_graph.entity_extractor
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS_DIR = REPO_ROOT / "data" / "processed" / "documents"
ONTOLOGY_SCHEMA = REPO_ROOT / "ontology" / "ontology_schema.json"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

SCIFACT_PREFIX = "SCIFACT_"

#: Hub node types: (node label, metadata field holding a single scalar value).
SCALAR_HUB_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("DocumentType", "document_type"),
    ("Department", "department"),
    ("CustomerScope", "customer_scope"),
    ("SourceAuthority", "source_authority"),
)

#: Properties copied verbatim from the document onto its Document node.
DOCUMENT_PROPERTIES: Tuple[str, ...] = (
    "title",
    "document_type",
    "version",
    "last_updated",
    "file_type",
    "source_authority",
)


def node_id(label: str, key: str) -> str:
    """Return the canonical node id for a label/key pair."""
    return f"{label}::{key}"


def load_documents(documents_dir: Path = DOCUMENTS_DIR) -> List[Dict[str, Any]]:
    """Load every canonical document JSON, sorted by filename for determinism."""
    paths = sorted(documents_dir.glob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No document JSON files found under {documents_dir}")
    documents = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            documents.append(json.load(handle))
    return documents


def load_category_catalog(schema_path: Path = ONTOLOGY_SCHEMA) -> Dict[str, Dict[str, str]]:
    """Load the code -> {name, name_source} catalog from the ontology schema."""
    with schema_path.open(encoding="utf-8") as handle:
        return json.load(handle)["category_catalog"]


def dataset_for(document_id: str) -> str:
    """Deterministic corpus of origin from the document id prefix."""
    return "SciFact" if document_id.startswith(SCIFACT_PREFIX) else "NovaTel"


class NodeCollector:
    """Accumulates nodes, collapsing repeat mentions of the same entity key."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self.mentions: int = 0  # every add() call, before deduplication
        self.collapsed: int = 0  # add() calls that hit an existing node

    def add(self, label: str, key: str, properties: Dict[str, Any]) -> str:
        """Register a node. Later mentions never overwrite the first one."""
        identifier = node_id(label, key)
        self.mentions += 1
        existing = self._nodes.get(identifier)
        if existing is None:
            self._nodes[identifier] = {
                "id": identifier,
                "label": label,
                "key": key,
                "properties": dict(properties),
            }
        else:
            self.collapsed += 1
        return identifier

    def nodes(self) -> List[Dict[str, Any]]:
        """Nodes sorted by (label, key) so output ordering is stable."""
        return sorted(self._nodes.values(), key=lambda node: (node["label"], node["key"]))

    @property
    def unique_count(self) -> int:
        return len(self._nodes)


def _document_properties(document: Dict[str, Any]) -> Dict[str, Any]:
    properties: Dict[str, Any] = {"document_id": document["document_id"]}
    for field in DOCUMENT_PROPERTIES:
        properties[field] = document.get(field) or ""
    properties["resolved"] = True
    properties["stub"] = False
    return properties


def stub_document_properties(document_id: str) -> Dict[str, Any]:
    """Properties for a Document node referenced by related_ids but never ingested."""
    properties: Dict[str, Any] = {"document_id": document_id}
    for field in DOCUMENT_PROPERTIES:
        properties[field] = ""
    properties["resolved"] = False
    properties["stub"] = True
    return properties


def extract_entities(
    documents: Iterable[Dict[str, Any]] | None = None,
    category_catalog: Dict[str, Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """Extract every node from the corpus.

    Returns a dict with ``nodes`` (deduplicated, sorted) and ``stats``.
    Stub Document nodes for dangling ``related_ids`` are created here too, so the
    node set is complete on its own; the relationship extractor only needs to
    emit edges against it.
    """
    documents = list(documents) if documents is not None else load_documents()
    catalog = category_catalog if category_catalog is not None else load_category_catalog()

    collector = NodeCollector()
    canonical_ids = {document["document_id"] for document in documents}

    for document in documents:
        document_id = document["document_id"]
        collector.add("Document", document_id, _document_properties(document))

        for label, field in SCALAR_HUB_FIELDS:
            value = document.get(field)
            if value:
                collector.add(label, value, {"name": value})

        category = document.get("category")
        if category:
            entry = catalog.get(category, {"name": category, "name_source": "unmapped"})
            collector.add(
                "Category",
                category,
                {
                    "code": category,
                    "name": entry.get("name", category),
                    "name_source": entry.get("name_source", "unmapped"),
                },
            )

        for tag in document.get("tags") or []:
            if tag:
                collector.add("Tag", tag, {"name": tag})

        dataset = dataset_for(document_id)
        collector.add("Dataset", dataset, {"name": dataset})

    # Dangling related_ids become stub Document nodes rather than being dropped.
    unresolved_ids = set()
    for document in documents:
        for related_id in document.get("related_ids") or []:
            if related_id and related_id not in canonical_ids:
                unresolved_ids.add(related_id)
                collector.add("Document", related_id, stub_document_properties(related_id))

    nodes = collector.nodes()
    counts: Dict[str, int] = {}
    for node in nodes:
        counts[node["label"]] = counts.get(node["label"], 0) + 1

    stats = {
        "documents_read": len(documents),
        "canonical_documents": len(canonical_ids),
        "stub_documents": len(unresolved_ids),
        "unique_nodes": collector.unique_count,
        "node_mentions": collector.mentions,
        "mentions_collapsed_by_dedup": collector.collapsed,
        "nodes_by_label": dict(sorted(counts.items())),
    }
    return {"nodes": nodes, "stats": stats, "canonical_ids": sorted(canonical_ids)}


def save_entities(
    result: Dict[str, Any],
    output_dir: Path = OUTPUT_DIR,
    filename: str = "nodes.json",
) -> Path:
    """Write nodes.json (nodes plus extraction stats).

    ``filename`` lets the builder keep the Phase 1 metadata-only dump in a
    separate file from the full Phase 2 graph.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    payload = {"stats": result["stats"], "nodes": result["nodes"]}
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def main() -> None:
    result = extract_entities()
    path = save_entities(result)
    stats = result["stats"]
    print(f"documents read        : {stats['documents_read']}")
    print(f"unique nodes          : {stats['unique_nodes']}")
    print(f"node mentions         : {stats['node_mentions']}")
    print(f"collapsed by dedup    : {stats['mentions_collapsed_by_dedup']}")
    for label, count in stats["nodes_by_label"].items():
        print(f"  {label:<16}: {count}")
    print(f"stub documents        : {stats['stub_documents']}")
    print(f"written               : {path}")


if __name__ == "__main__":
    main()
