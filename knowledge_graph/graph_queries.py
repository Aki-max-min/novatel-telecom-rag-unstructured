"""NetworkX queries over the built NovaTel knowledge graph.

Read-only helpers that answer the questions the graph was built to answer. Each
one takes the loaded graph and returns plain Python values, so they are usable
from a notebook, a test, or the demo at the bottom of this file.

Usage::

    python -m knowledge_graph.graph_queries
    python -m knowledge_graph.graph_queries --category C17 --service "KYC Verification"
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import networkx as nx

from knowledge_graph.graph_builder import CONTENT_NODE_LABELS, GRAPHML_PATH

MENTION_TYPES = {
    "Service": "MENTIONS_SERVICE",
    "Channel": "MENTIONS_CHANNEL",
    "VerificationMethod": "MENTIONS_VERIFICATION",
    "Requirement": "MENTIONS_REQUIREMENT",
    "Location": "MENTIONS_LOCATION",
}

COOCCURRENCE_TYPES = {
    "Channel": "AVAILABLE_VIA",
    "VerificationMethod": "REQUIRES_VERIFICATION",
    "Requirement": "REQUIRES_DOCUMENT",
}


def load_graph(path: Path = GRAPHML_PATH) -> nx.DiGraph:
    """Load the persisted graph. Build it first if this raises."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the graph first: python -m knowledge_graph.graph_builder"
        )
    return nx.read_graphml(path)


def _title(graph: nx.DiGraph, node: str) -> str:
    return graph.nodes[node].get("title") or graph.nodes[node].get("key", node)


def _is_resolved_document(graph: nx.DiGraph, node: str) -> bool:
    attributes = graph.nodes[node]
    if attributes.get("label") != "Document":
        return False
    resolved = attributes.get("resolved", True)
    return resolved if isinstance(resolved, bool) else str(resolved).lower() == "true"


def _owner_department(graph: nx.DiGraph, document: str) -> str:
    """The Department a document is owned by, or '' for a stub."""
    for _, target, attributes in graph.out_edges(document, data=True):
        if attributes.get("type") == "OWNED_BY_DEPARTMENT":
            return graph.nodes[target].get("key", "")
    return ""


def _in_neighbors(graph: nx.DiGraph, node: str, edge_type: str) -> List[str]:
    return [
        source
        for source, _, attributes in graph.in_edges(node, data=True)
        if attributes.get("type") == edge_type
    ]


def _out_neighbors(graph: nx.DiGraph, node: str, edge_type: str) -> List[str]:
    return [
        target
        for _, target, attributes in graph.out_edges(node, data=True)
        if attributes.get("type") == edge_type
    ]


# ---------------------------------------------------------------------------
# 1. Documents in a category
# ---------------------------------------------------------------------------
def documents_in_category(graph: nx.DiGraph, category_code: str) -> List[Dict[str, str]]:
    """Every document filed under a category code, e.g. ``C17``."""
    node = f"Category::{category_code}"
    if node not in graph:
        return []
    documents = _in_neighbors(graph, node, "BELONGS_TO_CATEGORY")
    return sorted(
        (
            {
                "document_id": graph.nodes[document].get("key", document),
                "title": _title(graph, document),
                "document_type": graph.nodes[document].get("document_type", ""),
                "department": _owner_department(graph, document),
            }
            for document in documents
        ),
        key=lambda row: row["document_id"],
    )


# ---------------------------------------------------------------------------
# 2. Documents mentioning a service
# ---------------------------------------------------------------------------
def documents_mentioning_service(
    graph: nx.DiGraph, service: str
) -> List[Dict[str, str]]:
    """Documents whose content mentions a service, with the matched evidence."""
    node = f"Service::{service}"
    if node not in graph:
        return []
    rows = []
    for source, _, attributes in graph.in_edges(node, data=True):
        if attributes.get("type") != "MENTIONS_SERVICE":
            continue
        rows.append(
            {
                "document_id": graph.nodes[source].get("key", source),
                "title": _title(graph, source),
                "matched_terms": attributes.get("matched_terms", ""),
                "match_count": attributes.get("match_count", 0),
                "evidence": attributes.get("evidence", ""),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["match_count"] or 0), row["document_id"]))


# ---------------------------------------------------------------------------
# 3. Two-hop neighbours of a document (shared Service or shared Tag)
# ---------------------------------------------------------------------------
def related_documents(
    graph: nx.DiGraph, document_id: str, via: Iterable[str] = ("Service", "Tag")
) -> List[Dict[str, Any]]:
    """Documents reachable in two hops through a shared Service or Tag.

    This is the query that makes the graph worth building: it connects documents
    that share a concept even when neither links to the other.
    """
    source = f"Document::{document_id}"
    if source not in graph:
        return []
    via = tuple(via)

    hubs: List[str] = []
    for _, target, attributes in graph.out_edges(source, data=True):
        label = graph.nodes[target].get("label")
        if label not in via:
            continue
        edge_type = attributes.get("type")
        if edge_type == "HAS_TAG" or str(edge_type).startswith("MENTIONS_"):
            hubs.append(target)

    shared: Dict[str, List[str]] = defaultdict(list)
    for hub in hubs:
        hub_label = graph.nodes[hub].get("label")
        edge_type = "HAS_TAG" if hub_label == "Tag" else MENTION_TYPES.get(hub_label)
        for neighbour in _in_neighbors(graph, hub, edge_type):
            if neighbour == source or not _is_resolved_document(graph, neighbour):
                continue
            shared[neighbour].append(f"{hub_label}:{graph.nodes[hub].get('key')}")

    rows = [
        {
            "document_id": graph.nodes[node].get("key", node),
            "title": _title(graph, node),
            "shared_count": len(links),
            "shared_via": sorted(links),
        }
        for node, links in shared.items()
    ]
    return sorted(rows, key=lambda row: (-row["shared_count"], row["document_id"]))


# ---------------------------------------------------------------------------
# 4. Service profile: what a service co-occurs with
# ---------------------------------------------------------------------------
def service_profile(graph: nx.DiGraph, service: str) -> Dict[str, Any]:
    """Channels, verification methods and requirements linked to a service.

    These come from the co-occurrence pass, so each entry carries its support
    (how many documents back it) - they are leads, not asserted facts.
    """
    node = f"Service::{service}"
    if node not in graph:
        return {}

    profile: Dict[str, Any] = {
        "service": service,
        "document_frequency": graph.nodes[node].get("document_frequency", 0),
    }
    for label, edge_type in COOCCURRENCE_TYPES.items():
        entries = []
        for _, target, attributes in graph.out_edges(node, data=True):
            if attributes.get("type") != edge_type:
                continue
            entries.append(
                {
                    "name": graph.nodes[target].get("key", target),
                    "support": int(attributes.get("support", 0) or 0),
                    "confidence": attributes.get("confidence", ""),
                    "evidence_document_ids": attributes.get("evidence_document_ids", ""),
                }
            )
        profile[label] = sorted(entries, key=lambda row: (-row["support"], row["name"]))
    return profile


# ---------------------------------------------------------------------------
# 5. Top hub nodes by degree
# ---------------------------------------------------------------------------
def top_hubs(
    graph: nx.DiGraph, limit: int = 15, exclude_labels: Iterable[str] = ("Document",)
) -> List[Tuple[str, str, int]]:
    """Highest-degree nodes, as (label, key, degree). Documents excluded by default."""
    exclude = set(exclude_labels)
    rows = [
        (
            attributes.get("label", "?"),
            attributes.get("key", node),
            graph.degree(node),
        )
        for node, attributes in graph.nodes(data=True)
        if attributes.get("label") not in exclude
    ]
    return sorted(rows, key=lambda row: (-row[2], row[0], row[1]))[:limit]


# ---------------------------------------------------------------------------
# 6. Documents owned by a department, optionally of one type
# ---------------------------------------------------------------------------
def documents_by_department(
    graph: nx.DiGraph, department: str, document_type: str | None = None
) -> List[Dict[str, str]]:
    """Documents a department owns, optionally filtered to one document type."""
    node = f"Department::{department}"
    if node not in graph:
        return []
    rows = []
    for document in _in_neighbors(graph, node, "OWNED_BY_DEPARTMENT"):
        attributes = graph.nodes[document]
        if document_type and attributes.get("document_type") != document_type:
            continue
        rows.append(
            {
                "document_id": attributes.get("key", document),
                "title": _title(graph, document),
                "document_type": attributes.get("document_type", ""),
            }
        )
    return sorted(rows, key=lambda row: row["document_id"])


# ---------------------------------------------------------------------------
# 7. Concept coverage per content label
# ---------------------------------------------------------------------------
def concept_coverage(graph: nx.DiGraph) -> Dict[str, List[Tuple[str, int]]]:
    """Every content concept with the number of documents mentioning it."""
    coverage: Dict[str, List[Tuple[str, int]]] = {}
    for label in CONTENT_NODE_LABELS:
        entries = [
            (
                attributes.get("key", node),
                len(_in_neighbors(graph, node, MENTION_TYPES[label])),
            )
            for node, attributes in graph.nodes(data=True)
            if attributes.get("label") == label
        ]
        coverage[label] = sorted(entries, key=lambda row: (-row[1], row[0]))
    return coverage


def _demo(graph: nx.DiGraph, category: str, service: str, document_id: str, department: str) -> None:
    print(f"=== 1. Documents in category {category} ===")
    for row in documents_in_category(graph, category)[:10]:
        print(f"  {row['document_id']:<22} {row['document_type']:<16} {row['title'][:60]}")

    print(f"\n=== 2. Documents mentioning service '{service}' ===")
    for row in documents_mentioning_service(graph, service)[:10]:
        print(f"  {row['document_id']:<22} x{row['match_count']:<3} via [{row['matched_terms']}]")

    print(f"\n=== 3. Documents 2 hops from {document_id} (shared Service or Tag) ===")
    for row in related_documents(graph, document_id)[:10]:
        print(f"  {row['document_id']:<22} shared={row['shared_count']} {row['shared_via']}")

    print(f"\n=== 4. Profile of service '{service}' (co-occurrence, heuristic) ===")
    profile = service_profile(graph, service)
    for label in ("Channel", "VerificationMethod", "Requirement"):
        entries = profile.get(label, [])
        rendered = ", ".join(f"{item['name']} (support={item['support']})" for item in entries)
        print(f"  {label:<19}: {rendered or '-'}")

    print("\n=== 5. Top hub nodes by degree ===")
    for label, key, degree in top_hubs(graph, limit=12):
        print(f"  {degree:>4}  {label:<18} {key}")

    print(f"\n=== 6. Documents owned by department '{department}' ===")
    for row in documents_by_department(graph, department)[:8]:
        print(f"  {row['document_id']:<22} {row['document_type']:<16} {row['title'][:55]}")

    print("\n=== 7. Concept coverage (documents per concept) ===")
    for label, entries in concept_coverage(graph).items():
        top = ", ".join(f"{name} ({count})" for name, count in entries[:5])
        print(f"  {label:<19}: {top}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the NovaTel knowledge graph.")
    parser.add_argument("--category", default="C17", help="Category code for query 1.")
    parser.add_argument("--service", default="KYC Verification", help="Service for queries 2 and 4.")
    parser.add_argument("--document", default="FAQ_C01_001", help="Document id for query 3.")
    parser.add_argument("--department", default="Network", help="Department for query 6.")
    args = parser.parse_args()

    graph = load_graph()
    print(f"loaded {graph.number_of_nodes()} nodes / {graph.number_of_edges()} edges\n")
    _demo(graph, args.category, args.service, args.document, args.department)


if __name__ == "__main__":
    main()
