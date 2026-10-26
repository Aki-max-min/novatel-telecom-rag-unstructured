"""Loads the NovaTel STRUCTURED knowledge graph into Neo4j.

Each row becomes a node carrying two labels: its EntityType (``:Customer``,
``:Invoice``, ``:CDR``, ...) so Cypher reads naturally, plus a shared
``:StructuredEntity`` label so the structured graph can be counted, matched and
deleted without touching the document KG if both are loaded into one database.

Writes are batched (1,000 rows per statement) because this graph is two orders
of magnitude bigger than the document one: 43,928 nodes and 31,027 edges.
Everything uses ``MERGE``, so loading twice leaves the database as loading once.

Connection settings are shared with the document loader:

    NEO4J_URI       (default bolt://localhost:7687)
    NEO4J_USER      (default neo4j)
    NEO4J_PASSWORD  (no default - must be set)
    NEO4J_DATABASE  (default neo4j)

Usage::

    python -m knowledge_graph.structured_graph_loader             # load + verify
    python -m knowledge_graph.structured_graph_loader --verify    # counts only
    python -m knowledge_graph.structured_graph_loader --reset     # delete first
    python -m knowledge_graph.structured_graph_loader --schema-graph  # also load schema view
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from knowledge_graph.graph_loader import (  # shared connection handling
    Neo4jUnavailable,
    STARTUP_HELP,
    connection_settings,
)
from knowledge_graph.graph_loader import _driver as open_driver
from knowledge_graph.structured_entity_extractor import ENTITY_TYPES
from knowledge_graph.structured_graph_builder import (
    INSTANCE_JSON_PATH,
    SCHEMA_JSON_PATH,
)
from knowledge_graph.structured_relationship_extractor import RELATIONSHIP_ORDER

#: Shared label so the structured graph is separable from the document KG.
SHARED_LABEL = "StructuredEntity"

#: Labels and relationship types that may be written. Neo4j cannot parameterise
#: either, so they are interpolated - these allow-lists are what makes that safe.
ALLOWED_LABELS = frozenset(ENTITY_TYPES.values()) | {SHARED_LABEL, "EntityType", "StructuredCategory"}
ALLOWED_RELATIONSHIPS = frozenset(RELATIONSHIP_ORDER) | {"IN_CATEGORY"}

BATCH_SIZE = 1000


def load_payload(path: Path = INSTANCE_JSON_PATH) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build it first: "
            f"python -m knowledge_graph.structured_graph_builder"
        )
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _batched(rows: List[Dict[str, Any]], size: int = BATCH_SIZE) -> Iterable[List[Dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _node_rows(nodes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group instance nodes by EntityType label."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for node in nodes:
        label = node.get("entity_type") or node["properties"].get("entity_type")
        if label not in ALLOWED_LABELS:
            raise ValueError(f"refusing to write unknown label {label!r}")
        grouped.setdefault(label, []).append(
            {"id": node["id"], "props": dict(node["properties"])}
        )
    return grouped


def _edge_rows(edges: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges:
        relationship = edge["type"]
        if relationship not in ALLOWED_RELATIONSHIPS:
            raise ValueError(f"refusing to write unknown relationship {relationship!r}")
        properties = dict(edge.get("properties", {}))
        properties["source_field"] = edge.get("source_field", "")
        grouped.setdefault(relationship, []).append(
            {"source": edge["source"], "target": edge["target"], "props": properties}
        )
    return grouped


def ensure_constraints(session, labels: Iterable[str]) -> None:
    """Uniqueness on id per label - also the index MERGE needs to stay fast."""
    for label in sorted(set(labels)):
        session.run(
            f"CREATE CONSTRAINT novatel_struct_{label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )


def reset_structured(session) -> int:
    """Delete only the structured graph, in batches; the document KG is untouched."""
    deleted = 0
    while True:
        record = session.run(
            f"MATCH (n:{SHARED_LABEL}) WITH n LIMIT {BATCH_SIZE * 5} "
            f"DETACH DELETE n RETURN count(n) AS deleted"
        ).single()
        removed = record["deleted"] if record else 0
        deleted += removed
        if removed == 0:
            return deleted


def _counts(session) -> Dict[str, int]:
    """Verification query, scoped to the structured graph."""
    nodes = session.run(
        f"MATCH (n:{SHARED_LABEL}) RETURN count(n) AS nodes"
    ).single()["nodes"]
    relationships = session.run(
        f"MATCH (:{SHARED_LABEL})-[r]->(:{SHARED_LABEL}) RETURN count(r) AS relationships"
    ).single()["relationships"]
    return {"nodes": nodes, "relationships": relationships}


def fetch_counts() -> Optional[Dict[str, int]]:
    """Structured-graph counts from Neo4j, or None when it is unavailable."""
    try:
        settings = connection_settings()
        driver = open_driver(settings)
    except Neo4jUnavailable:
        return None
    try:
        with driver.session(database=settings["database"]) as session:
            return _counts(session)
    except Exception:  # noqa: BLE001 - Neo4j is optional; never raise from here
        return None
    finally:
        driver.close()


def load_into_neo4j(
    payload: Dict[str, Any],
    reset: bool = False,
    schema_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """MERGE every instance node and FK edge into Neo4j, then verify."""
    settings = connection_settings()
    driver = open_driver(settings)

    nodes_by_label = _node_rows(payload["nodes"])
    edges_by_type = _edge_rows(payload["edges"])

    written_nodes = written_edges = 0
    try:
        with driver.session(database=settings["database"]) as session:
            ensure_constraints(session, nodes_by_label)
            if reset:
                removed = reset_structured(session)
                print(f"  reset: deleted {removed} pre-existing structured node(s)")

            for label, rows in sorted(nodes_by_label.items()):
                for batch in _batched(rows):
                    session.run(
                        f"UNWIND $rows AS row "
                        f"MERGE (n:{label}:{SHARED_LABEL} {{id: row.id}}) "
                        f"SET n += row.props",
                        rows=batch,
                    )
                written_nodes += len(rows)
                print(f"  merged {len(rows):>6} :{label}")

            for relationship, rows in sorted(edges_by_type.items()):
                for batch in _batched(rows):
                    session.run(
                        f"UNWIND $rows AS row "
                        f"MATCH (a:{SHARED_LABEL} {{id: row.source}}) "
                        f"MATCH (b:{SHARED_LABEL} {{id: row.target}}) "
                        f"MERGE (a)-[r:{relationship}]->(b) "
                        f"SET r += row.props",
                        rows=batch,
                    )
                written_edges += len(rows)
                print(f"  merged {len(rows):>6} -[:{relationship}]->")

            if schema_payload:
                for node in schema_payload["nodes"]:
                    label = node["label"]
                    if label not in ALLOWED_LABELS:
                        raise ValueError(f"refusing to write unknown label {label!r}")
                    session.run(
                        f"MERGE (n:{label} {{id: $id}}) SET n += $props",
                        id=node["id"],
                        props=node["properties"],
                    )
                for edge in schema_payload["edges"]:
                    relationship = edge["type"]
                    if relationship not in ALLOWED_RELATIONSHIPS:
                        raise ValueError(
                            f"refusing to write unknown relationship {relationship!r}"
                        )
                    session.run(
                        f"MATCH (a {{id: $source}}) MATCH (b {{id: $target}}) "
                        f"MERGE (a)-[r:{relationship} {{source_field: $field}}]->(b)",
                        source=edge["source"],
                        target=edge["target"],
                        field=edge["source_field"],
                    )
                print(
                    f"  merged schema view: {len(schema_payload['nodes'])} nodes / "
                    f"{len(schema_payload['edges'])} edges"
                )

            counts = _counts(session)
    finally:
        driver.close()

    return {
        "written_nodes": written_nodes,
        "written_edges": written_edges,
        "neo4j_nodes": counts["nodes"],
        "neo4j_relationships": counts["relationships"],
        "uri": settings["uri"],
        "database": settings["database"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load the NovaTel structured KG into Neo4j."
    )
    parser.add_argument("--verify", action="store_true", help="Report counts only; write nothing.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing :StructuredEntity nodes before loading (destructive).",
    )
    parser.add_argument(
        "--schema-graph",
        action="store_true",
        help="Also load the schema/ontology view (EntityType + StructuredCategory nodes).",
    )
    args = parser.parse_args()

    settings = connection_settings()
    print(f"target: {settings['uri']} (database {settings['database']}, user {settings['user']})")

    if args.verify:
        counts = fetch_counts()
        if counts is None:
            print("Neo4j not reachable.\n", file=sys.stderr)
            print(STARTUP_HELP)
            return 2
        print(f"neo4j_nodes: {counts['nodes']}")
        print(f"neo4j_relationships: {counts['relationships']}")
        return 0

    payload = load_payload()
    schema_payload = None
    if args.schema_graph:
        with SCHEMA_JSON_PATH.open(encoding="utf-8") as handle:
            schema_payload = json.load(handle)

    print(
        f"source: {INSTANCE_JSON_PATH.name} "
        f"({len(payload['nodes'])} nodes, {len(payload['edges'])} edges)"
    )

    try:
        result = load_into_neo4j(payload, reset=args.reset, schema_payload=schema_payload)
    except Neo4jUnavailable as error:
        print(f"Neo4j not reachable: {error}\n", file=sys.stderr)
        print(STARTUP_HELP)
        return 2

    print("===== NEO4J STRUCTURED LOAD VERIFICATION =====")
    print(f"merged_nodes: {result['written_nodes']}")
    print(f"merged_relationships: {result['written_edges']}")
    print(f"neo4j_nodes: {result['neo4j_nodes']}")
    print(f"neo4j_relationships: {result['neo4j_relationships']}")
    print("(counts are scoped to :StructuredEntity, so the document KG is excluded)")
    print("==============================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
