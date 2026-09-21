"""Deterministic edge extraction for the NovaTel knowledge graph.

Every edge is derived from exactly one metadata field of a canonical document,
so the edge set is fully reproducible. Dangling ``related_ids`` are preserved:
when a related id is not one of the canonical document ids, the RELATED_TO edge
is still written and its target is the stub Document node (``resolved=false``)
created by :mod:`knowledge_graph.entity_extractor`.

Run standalone to write ``knowledge_graph/output/edges.json``::

    python -m knowledge_graph.relationship_extractor
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from knowledge_graph.entity_extractor import (
    OUTPUT_DIR,
    dataset_for,
    load_documents,
    node_id,
)

#: (relationship type, target label, metadata field) for one-valued fields.
SCALAR_RELATIONSHIPS: Tuple[Tuple[str, str, str], ...] = (
    ("BELONGS_TO_CATEGORY", "Category", "category"),
    ("IS_TYPE", "DocumentType", "document_type"),
    ("OWNED_BY_DEPARTMENT", "Department", "department"),
    ("APPLIES_TO_SCOPE", "CustomerScope", "customer_scope"),
    ("AUTHORED_BY", "SourceAuthority", "source_authority"),
)


def _edge(
    source: str,
    target: str,
    edge_type: str,
    source_field: str,
    **properties: Any,
) -> Dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "type": edge_type,
        "source_field": source_field,
        "properties": properties,
    }


def extract_relationships(
    documents: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Extract every edge from the corpus.

    Returns a dict with ``edges`` (ordered by document, then relationship type)
    and ``stats`` including the related_ids resolution counters.
    """
    documents = list(documents) if documents is not None else load_documents()
    canonical_ids = {document["document_id"] for document in documents}

    edges: List[Dict[str, Any]] = []
    related_total = 0
    related_unresolved = 0
    unresolved_targets = set()

    for document in documents:
        document_id = document["document_id"]
        source = node_id("Document", document_id)

        for edge_type, target_label, field in SCALAR_RELATIONSHIPS:
            value = document.get(field)
            if value:
                edges.append(
                    _edge(source, node_id(target_label, value), edge_type, field)
                )

        for tag in document.get("tags") or []:
            if tag:
                edges.append(_edge(source, node_id("Tag", tag), "HAS_TAG", "tags"))

        dataset = dataset_for(document_id)
        edges.append(
            _edge(source, node_id("Dataset", dataset), "PART_OF_DATASET", "document_id")
        )

        for related_id in document.get("related_ids") or []:
            if not related_id:
                continue
            related_total += 1
            resolved = related_id in canonical_ids
            if not resolved:
                related_unresolved += 1
                unresolved_targets.add(related_id)
            edges.append(
                _edge(
                    source,
                    node_id("Document", related_id),
                    "RELATED_TO",
                    "related_ids",
                    resolved=resolved,
                )
            )

    counts: Dict[str, int] = {}
    for edge in edges:
        counts[edge["type"]] = counts.get(edge["type"], 0) + 1

    unresolved_rate = (related_unresolved / related_total) if related_total else 0.0
    stats = {
        "documents_read": len(documents),
        "total_edges": len(edges),
        "edges_by_type": dict(sorted(counts.items())),
        "related_ids_total": related_total,
        "related_ids_unresolved": related_unresolved,
        "related_ids_resolved": related_total - related_unresolved,
        "distinct_unresolved_targets": len(unresolved_targets),
        "unresolved_rate": round(unresolved_rate, 4),
    }
    return {
        "edges": edges,
        "stats": stats,
        "unresolved_targets": sorted(unresolved_targets),
    }


def save_relationships(
    result: Dict[str, Any],
    output_dir: Path = OUTPUT_DIR,
    filename: str = "edges.json",
) -> Path:
    """Write edges.json (edges plus extraction stats).

    ``filename`` lets the builder keep the Phase 1 metadata-only dump in a
    separate file from the full Phase 2 graph.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    payload = {
        "stats": result["stats"],
        "unresolved_targets": result["unresolved_targets"],
        "edges": result["edges"],
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def main() -> None:
    result = extract_relationships()
    path = save_relationships(result)
    stats = result["stats"]
    print(f"documents read        : {stats['documents_read']}")
    print(f"total edges           : {stats['total_edges']}")
    for edge_type, count in stats["edges_by_type"].items():
        print(f"  {edge_type:<20}: {count}")
    print(f"related_ids total     : {stats['related_ids_total']}")
    print(f"related_ids unresolved: {stats['related_ids_unresolved']}")
    print(f"unresolved rate       : {stats['unresolved_rate']}")
    print(f"written               : {path}")


if __name__ == "__main__":
    main()
