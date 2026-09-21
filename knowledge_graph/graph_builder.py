"""Builds the NovaTel knowledge graph from the deterministic extractors.

Assembles a ``networkx.MultiDiGraph`` and writes it to ``knowledge_graph/output/``:

* ``novatel_kg.graphml`` - portable graph interchange (Gephi, yEd, Neo4j import)
* ``graph.json``         - nodes/edges with full properties, plus build stats

Two build modes:

* **full** (default) - Phase 1 metadata layer + Phase 2 content layer.
* **metadata-only** (``--metadata-only``) - the Phase 1 graph exactly as it was,
  written to ``*_metadata_only.*`` files so the Phase 1 numbers stay
  reproducible and are never overwritten by the richer build.

A MultiDiGraph is used because two nodes can be connected by more than one
relationship type, and the graph is directed (Document -> hub/concept).

Usage::

    python -m knowledge_graph.graph_builder                  # metadata + content
    python -m knowledge_graph.graph_builder --metadata-only  # Phase 1 only
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import networkx as nx

from knowledge_graph.content_extractor import extract_content, save_content
from knowledge_graph.entity_extractor import (
    OUTPUT_DIR,
    extract_entities,
    load_documents,
    save_entities,
)
from knowledge_graph.relationship_extractor import (
    extract_relationships,
    save_relationships,
)

GRAPHML_PATH = OUTPUT_DIR / "novatel_kg.graphml"
GRAPH_JSON_PATH = OUTPUT_DIR / "graph.json"
METADATA_ONLY_GRAPHML_PATH = OUTPUT_DIR / "novatel_kg_metadata_only.graphml"

#: Node labels and relationship types contributed by each layer, so the
#: evaluator can slice the graph back apart without re-reading the corpus.
METADATA_NODE_LABELS = (
    "Document",
    "DocumentType",
    "Category",
    "Department",
    "CustomerScope",
    "Tag",
    "SourceAuthority",
    "Dataset",
)
CONTENT_NODE_LABELS = (
    "Service",
    "Channel",
    "VerificationMethod",
    "Requirement",
    "Location",
)
CONTENT_EDGE_TYPES = (
    "MENTIONS_SERVICE",
    "MENTIONS_CHANNEL",
    "MENTIONS_VERIFICATION",
    "MENTIONS_REQUIREMENT",
    "MENTIONS_LOCATION",
    "AVAILABLE_VIA",
    "REQUIRES_VERIFICATION",
    "REQUIRES_DOCUMENT",
)


def _graphml_safe(value: Any) -> Any:
    """GraphML only carries scalars; render anything else as a string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def build_graph(
    entities: Dict[str, Any] | None = None,
    relationships: Dict[str, Any] | None = None,
    content: Dict[str, Any] | None = None,
) -> nx.MultiDiGraph:
    """Assemble the graph.

    Nodes are added before edges, so no edge can silently create an implicit
    node. Pass ``content=None`` to build the Phase 1 metadata graph only.
    """
    if entities is None or relationships is None:
        documents = load_documents()
        entities = entities or extract_entities(documents)
        relationships = relationships or extract_relationships(documents)

    graph = nx.MultiDiGraph()
    graph.graph["name"] = "NovaTel Unstructured KG"
    graph.graph["schema_version"] = "2.0.0" if content else "1.0.0"
    graph.graph["layers"] = "metadata+content" if content else "metadata"

    all_nodes: List[Dict[str, Any]] = list(entities["nodes"])
    all_edges: List[Dict[str, Any]] = list(relationships["edges"])
    if content:
        all_nodes += content["nodes"]
        all_edges += content["edges"]

    for node in all_nodes:
        attributes = {"label": node["label"], "key": node["key"]}
        attributes["layer"] = (
            "content" if node["label"] in CONTENT_NODE_LABELS else "metadata"
        )
        for name, value in node["properties"].items():
            attributes[name] = _graphml_safe(value)
        graph.add_node(node["id"], **attributes)

    known = set(graph.nodes)
    missing = [
        edge
        for edge in all_edges
        if edge["source"] not in known or edge["target"] not in known
    ]
    if missing:
        raise ValueError(
            f"{len(missing)} edge(s) reference nodes absent from the node set, "
            f"first: {missing[0]}"
        )

    for edge in all_edges:
        attributes = {
            "type": edge["type"],
            "source_field": edge["source_field"],
            "layer": "content" if edge["type"] in CONTENT_EDGE_TYPES else "metadata",
        }
        for name, value in edge.get("properties", {}).items():
            attributes[name] = _graphml_safe(value)
        graph.add_edge(edge["source"], edge["target"], key=edge["type"], **attributes)

    # A MultiDiGraph keyed on relationship type would silently merge two identical
    # (source, target, type) triples. Fail loudly instead of under-reporting edges.
    if graph.number_of_edges() != len(all_edges):
        raise ValueError(
            f"edge collapse detected: extracted {len(all_edges)} edges "
            f"but the graph holds {graph.number_of_edges()}"
        )

    return graph


def save_graph(
    graph: nx.MultiDiGraph,
    entities: Dict[str, Any],
    relationships: Dict[str, Any],
    content: Dict[str, Any] | None = None,
    output_dir: Path = OUTPUT_DIR,
) -> Dict[str, Path]:
    """Write graphml plus a nodes/edges JSON, and the per-extractor dumps.

    Metadata-only builds are written under ``*_metadata_only.*`` names so they
    never clobber the full graph (and vice versa).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if content else "_metadata_only"

    graphml_path = output_dir / f"novatel_kg{suffix}.graphml"
    nx.write_graphml(graph, graphml_path)

    nodes = list(entities["nodes"]) + (list(content["nodes"]) if content else [])
    edges = list(relationships["edges"]) + (list(content["edges"]) if content else [])

    graph_json_path = output_dir / f"graph{suffix}.json"
    payload = {
        "graph": dict(graph.graph),
        "stats": {
            "entity_extraction": entities["stats"],
            "relationship_extraction": relationships["stats"],
            "content_extraction": content["stats"] if content else None,
            "graph": {
                "total_nodes": graph.number_of_nodes(),
                "total_edges": graph.number_of_edges(),
            },
        },
        "nodes": nodes,
        "edges": edges,
    }
    with graph_json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    written = {
        "graphml": graphml_path,
        "graph_json": graph_json_path,
        "nodes_json": save_entities(entities, output_dir, f"nodes{suffix}.json"),
        "edges_json": save_relationships(relationships, output_dir, f"edges{suffix}.json"),
    }
    if content:
        written["content_json"] = save_content(content, output_dir)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the NovaTel knowledge graph.")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Build the Phase 1 metadata graph only (no content layer).",
    )
    args = parser.parse_args()

    documents = load_documents()
    entities = extract_entities(documents)
    relationships = extract_relationships(documents)
    content = None if args.metadata_only else extract_content(documents)

    graph = build_graph(entities, relationships, content)
    written = save_graph(graph, entities, relationships, content)

    mode = "METADATA ONLY (PHASE 1)" if args.metadata_only else "METADATA + CONTENT"
    print(f"===== NOVATEL KG - BUILD [{mode}] =====")
    print(f"documents read : {len(documents)}")
    print(f"nodes          : {graph.number_of_nodes()}")
    print(f"edges          : {graph.number_of_edges()}")
    for label, count in entities["stats"]["nodes_by_label"].items():
        print(f"  node {label:<20}: {count}")
    if content:
        for label, count in content["stats"]["content_nodes_by_type"].items():
            print(f"  node {label:<20}: {count}")
    for edge_type, count in relationships["stats"]["edges_by_type"].items():
        print(f"  edge {edge_type:<22}: {count}")
    if content:
        for edge_type, count in content["stats"]["content_edges_by_type"].items():
            print(f"  edge {edge_type:<22}: {count}")
    print("written:")
    for name, path in written.items():
        print(f"  {name:<13}: {path}")
    print("=" * 46)


if __name__ == "__main__":
    main()
