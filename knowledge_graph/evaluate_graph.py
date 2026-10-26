"""Loads the built NovaTel knowledge graph and prints the stats report.

Everything is read back off the persisted graph (``novatel_kg.graphml``), not
recomputed from the corpus, so the report describes what was actually built.

Two blocks are printed:

* **PHASE 1 STATS** - computed over the *metadata subgraph* (nodes and edges
  tagged ``layer="metadata"``), so the Phase 1 numbers stay directly comparable
  to the Phase 1 run even though the graph now carries a content layer too.
* **PHASE 2 STATS** - the whole graph, plus the content layer breakdown, the
  FAQ_C01_001 ground-truth spotcheck and the Neo4j load verification.

Usage::

    python -m knowledge_graph.evaluate_graph
    python -m knowledge_graph.evaluate_graph --metadata-only   # Phase 1 graph
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

import networkx as nx

from knowledge_graph.graph_builder import (
    CONTENT_EDGE_TYPES,
    CONTENT_NODE_LABELS,
    GRAPHML_PATH,
    METADATA_ONLY_GRAPHML_PATH,
)

GROUND_TRUTH_DOCUMENT = "FAQ_C01_001"

#: Printed in this order so the block shape is stable across runs.
NODE_TYPE_ORDER = (
    "Document",
    "DocumentType",
    "Category",
    "Department",
    "CustomerScope",
    "Tag",
    "SourceAuthority",
    "Dataset",
    "StubDocument(unresolved)",
)

EDGE_TYPE_ORDER = (
    "BELONGS_TO_CATEGORY",
    "IS_TYPE",
    "OWNED_BY_DEPARTMENT",
    "APPLIES_TO_SCOPE",
    "HAS_TAG",
    "AUTHORED_BY",
    "PART_OF_DATASET",
    "RELATED_TO",
)

#: Spotcheck lines, in the order the report prints them.
SPOTCHECK_ORDER = (
    ("services", "Service"),
    ("channels", "Channel"),
    ("verification_methods", "VerificationMethod"),
    ("locations", "Location"),
    ("requirements", "Requirement"),
)


def load_graph(path: Path = GRAPHML_PATH) -> nx.MultiDiGraph:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the graph first: python -m knowledge_graph.graph_builder"
        )
    return nx.read_graphml(path)


def _is_true(value: Any) -> bool:
    """GraphML may hand back a real bool or the string 'True'/'true'."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def metadata_subgraph(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """The Phase 1 layer on its own: metadata nodes and metadata edges only."""
    nodes = [
        node
        for node, attributes in graph.nodes(data=True)
        if attributes.get("label") not in CONTENT_NODE_LABELS
    ]
    subgraph = graph.subgraph(nodes).copy()
    # read_graphml hands back a DiGraph when the file holds no parallel edges,
    # so the edge view is addressed with or without keys depending on the type.
    if subgraph.is_multigraph():
        content_edges = [
            (source, target, key)
            for source, target, key, attributes in subgraph.edges(keys=True, data=True)
            if attributes.get("type") in CONTENT_EDGE_TYPES
        ]
    else:
        content_edges = [
            (source, target)
            for source, target, attributes in subgraph.edges(data=True)
            if attributes.get("type") in CONTENT_EDGE_TYPES
        ]
    subgraph.remove_edges_from(content_edges)
    return subgraph


def compute_stats(graph: nx.MultiDiGraph) -> Dict[str, Any]:
    """Phase 1 statistics over whichever graph is handed in."""
    node_counts: Counter = Counter()
    key_counts: Counter = Counter()

    for _, attributes in graph.nodes(data=True):
        label = attributes.get("label", "Unknown")
        if label == "Document" and not _is_true(attributes.get("resolved", True)):
            node_counts["StubDocument(unresolved)"] += 1
        else:
            node_counts[label] += 1
        key_counts[(label, attributes.get("key"))] += 1

    edge_counts: Counter = Counter()
    related_total = 0
    related_unresolved = 0
    for _, _, attributes in graph.edges(data=True):
        edge_type = attributes.get("type", "UNKNOWN")
        edge_counts[edge_type] += 1
        if edge_type == "RELATED_TO":
            related_total += 1
            if not _is_true(attributes.get("resolved", True)):
                related_unresolved += 1

    total_nodes = graph.number_of_nodes()
    total_edges = graph.number_of_edges()

    # Duplicate entities surviving into the graph: any (label, key) pair carried
    # by more than one node. Deterministic dedup should keep this at 0.0.
    duplicate_nodes = sum(count for count in key_counts.values() if count > 1)
    duplicate_node_rate = (duplicate_nodes / total_nodes) if total_nodes else 0.0

    average_degree = (2 * total_edges / total_nodes) if total_nodes else 0.0
    components = nx.number_connected_components(graph.to_undirected(as_view=False))
    unresolved_rate = (related_unresolved / related_total) if related_total else 0.0

    return {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "nodes_by_type": {name: node_counts.get(name, 0) for name in NODE_TYPE_ORDER},
        "edges_by_type": {name: edge_counts.get(name, 0) for name in EDGE_TYPE_ORDER},
        "average_degree": round(average_degree, 4),
        "connected_components": components,
        "duplicate_node_rate": round(duplicate_node_rate, 4),
        "related_ids_total": related_total,
        "related_ids_unresolved": related_unresolved,
        "unresolved_rate": round(unresolved_rate, 4),
        "unexpected_node_types": {
            name: count
            for name, count in node_counts.items()
            if name not in NODE_TYPE_ORDER and name not in CONTENT_NODE_LABELS
        },
        "unexpected_edge_types": {
            name: count
            for name, count in edge_counts.items()
            if name not in EDGE_TYPE_ORDER and name not in CONTENT_EDGE_TYPES
        },
        "duplicate_nodes": duplicate_nodes,
    }


def spotcheck(graph: nx.MultiDiGraph, document_id: str) -> Dict[str, List[str]]:
    """Concepts reachable from one document over MENTIONS_* edges, read from the graph."""
    source = f"Document::{document_id}"
    found: Dict[str, List[str]] = {label: [] for _, label in SPOTCHECK_ORDER}
    if source not in graph:
        return found
    for _, target, attributes in graph.out_edges(source, data=True):
        if not str(attributes.get("type", "")).startswith("MENTIONS_"):
            continue
        label = graph.nodes[target].get("label")
        if label in found:
            found[label].append(graph.nodes[target].get("key", target))
    return {label: sorted(names) for label, names in found.items()}


def compute_content_stats(graph: nx.MultiDiGraph) -> Dict[str, Any]:
    """Phase 2 statistics over the full graph."""
    node_counts: Counter = Counter()
    for _, attributes in graph.nodes(data=True):
        label = attributes.get("label")
        if label in CONTENT_NODE_LABELS:
            node_counts[label] += 1

    edge_counts: Counter = Counter()
    documents_with_content: set = set()
    for source, _, attributes in graph.edges(data=True):
        edge_type = attributes.get("type")
        if edge_type in CONTENT_EDGE_TYPES:
            edge_counts[edge_type] += 1
            if str(edge_type).startswith("MENTIONS_"):
                documents_with_content.add(source)

    canonical_documents = sum(
        1
        for _, attributes in graph.nodes(data=True)
        if attributes.get("label") == "Document"
        and _is_true(attributes.get("resolved", True))
    )

    return {
        "total_nodes": graph.number_of_nodes(),
        "total_edges": graph.number_of_edges(),
        "content_nodes_by_type": {
            name: node_counts.get(name, 0) for name in CONTENT_NODE_LABELS
        },
        "content_edges_by_type": {
            name: edge_counts.get(name, 0) for name in CONTENT_EDGE_TYPES
        },
        "documents_with_content_edge": len(documents_with_content),
        "canonical_documents": canonical_documents,
        "spotcheck": spotcheck(graph, GROUND_TRUTH_DOCUMENT),
    }


def neo4j_counts() -> Dict[str, Any]:
    """Live node/relationship counts from Neo4j, or 'not run' if unreachable.

    Never raises: Neo4j is optional, and a missing driver or a stopped server
    must not fail the report.
    """
    try:
        from knowledge_graph.graph_loader import fetch_counts

        counts = fetch_counts()
    except Exception:  # noqa: BLE001 - any failure means "Neo4j not available"
        counts = None
    if not counts:
        return {"nodes": "not run", "relationships": "not run"}
    return {"nodes": counts["nodes"], "relationships": counts["relationships"]}


def print_report(stats: Dict[str, Any]) -> None:
    print("===== NOVATEL KG — PHASE 1 STATS =====")
    print(f"total_nodes: {stats['total_nodes']}")
    print(f"total_edges: {stats['total_edges']}")
    print("nodes_by_type:")
    for name in NODE_TYPE_ORDER:
        print(f"  {name}: {stats['nodes_by_type'][name]}")
    print("edges_by_type:")
    for name in EDGE_TYPE_ORDER:
        print(f"  {name}: {stats['edges_by_type'][name]}")
    print(f"average_degree: {stats['average_degree']}")
    print(f"connected_components(undirected): {stats['connected_components']}")
    print(f"duplicate_node_rate: {stats['duplicate_node_rate']}")
    print(f"related_ids_total: {stats['related_ids_total']}")
    print(f"related_ids_unresolved: {stats['related_ids_unresolved']}")
    print(f"unresolved_rate: {stats['unresolved_rate']}")
    print("=======================================")


def print_phase2_report(stats: Dict[str, Any], neo4j: Dict[str, Any]) -> None:
    print("===== NOVATEL KG — PHASE 2 STATS =====")
    print(f"total_nodes: {stats['total_nodes']}")
    print(f"total_edges: {stats['total_edges']}")
    print("content_nodes_by_type:")
    for name in CONTENT_NODE_LABELS:
        print(f"  {name}: {stats['content_nodes_by_type'][name]}")
    print("content_edges_by_type:")
    for name in CONTENT_EDGE_TYPES:
        print(f"  {name}: {stats['content_edges_by_type'][name]}")
    print(
        "documents_with_at_least_one_content_edge: "
        f"{stats['documents_with_content_edge']} / {stats['canonical_documents']}"
    )
    print(f"--- GROUND TRUTH SPOTCHECK: {GROUND_TRUTH_DOCUMENT} ---")
    for line_name, label in SPOTCHECK_ORDER:
        print(f"{line_name}: {stats['spotcheck'][label]}")
    print("--- NEO4J ---")
    print(f"neo4j_nodes: {neo4j['nodes']}")
    print(f"neo4j_relationships: {neo4j['relationships']}")
    print("=======================================")


def print_notes(stats: Dict[str, Any], source: Path) -> None:
    """Context that does not belong inside the fixed stats blocks."""
    print()
    print("notes:")
    print(
        "  The PHASE 1 block is computed over the metadata subgraph (layer=metadata), "
        "so its numbers stay identical to the Phase 1 run."
    )
    print(
        "  duplicate_node_rate counts (label, key) pairs held by more than one node; "
        f"0.0 means deduplication is clean ({stats['duplicate_nodes']} duplicates found)."
    )
    print(
        "  Stub documents come from related_ids that match none of the canonical "
        "document_ids. They are kept as Document nodes with resolved=false, never dropped."
    )
    print(
        "  AVAILABLE_VIA / REQUIRES_VERIFICATION / REQUIRES_DOCUMENT are co-occurrence "
        "heuristics (confidence=cooccurrence), not asserted facts."
    )
    if stats["unexpected_node_types"]:
        print(f"  WARNING unexpected node types: {stats['unexpected_node_types']}")
    if stats["unexpected_edge_types"]:
        print(f"  WARNING unexpected edge types: {stats['unexpected_edge_types']}")
    print(f"  source graph: {source}")


def _force_utf8_stdout() -> None:
    """The stats block contains an em dash; Windows consoles default to cp1252."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main() -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Evaluate the NovaTel knowledge graph.")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Evaluate the Phase 1 metadata-only graph and print just the Phase 1 block.",
    )
    parser.add_argument(
        "--skip-neo4j",
        action="store_true",
        help="Do not attempt to reach Neo4j; report the counts as 'not run'.",
    )
    args = parser.parse_args()

    source = METADATA_ONLY_GRAPHML_PATH if args.metadata_only else GRAPHML_PATH
    try:
        graph = load_graph(source)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1

    phase1_stats = compute_stats(metadata_subgraph(graph))
    print_report(phase1_stats)

    if not args.metadata_only:
        print()
        neo4j = (
            {"nodes": "not run", "relationships": "not run"}
            if args.skip_neo4j
            else neo4j_counts()
        )
        print_phase2_report(compute_content_stats(graph), neo4j)

    print_notes(phase1_stats, source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
