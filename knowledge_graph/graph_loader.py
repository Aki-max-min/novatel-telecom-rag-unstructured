"""Mirrors the built NovaTel knowledge graph into Neo4j.

Reads ``knowledge_graph/output/graph.json`` (the merged metadata + content
graph) and MERGEs every node and relationship into Neo4j, so running the loader
twice leaves the database in the same state as running it once.

Connection settings come from the environment::

    NEO4J_URI       (default bolt://localhost:7687)
    NEO4J_USER      (default neo4j)
    NEO4J_PASSWORD  (no default - must be set)
    NEO4J_DATABASE  (default neo4j)

Usage::

    python -m knowledge_graph.graph_loader            # load, then verify
    python -m knowledge_graph.graph_loader --verify   # counts only, no writes
    python -m knowledge_graph.graph_loader --reset    # delete this graph first

If Neo4j is not running the loader exits with a clear message and instructions
rather than a stack trace; nothing else in the pipeline depends on it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from knowledge_graph.graph_builder import (
    CONTENT_EDGE_TYPES,
    CONTENT_NODE_LABELS,
    GRAPH_JSON_PATH,
    METADATA_NODE_LABELS,
)

DEFAULT_URI = "bolt://localhost:7687"
DEFAULT_USER = "neo4j"
DEFAULT_DATABASE = "neo4j"

#: Only these labels and types are ever written. Neo4j cannot parameterise a
#: label or relationship type, so they are interpolated into Cypher - the
#: allow-lists below are what keeps that safe.
ALLOWED_LABELS = frozenset(METADATA_NODE_LABELS) | frozenset(CONTENT_NODE_LABELS)
ALLOWED_RELATIONSHIPS = frozenset(
    (
        "BELONGS_TO_CATEGORY",
        "IS_TYPE",
        "OWNED_BY_DEPARTMENT",
        "APPLIES_TO_SCOPE",
        "HAS_TAG",
        "AUTHORED_BY",
        "PART_OF_DATASET",
        "RELATED_TO",
    )
) | frozenset(CONTENT_EDGE_TYPES)

BATCH_SIZE = 500
CONNECTION_TIMEOUT = 5.0

STARTUP_HELP = """
Neo4j is not reachable. To start it and load the graph:

  Option A - Neo4j Desktop (easiest on Windows)
    1. Download and install Neo4j Desktop: https://neo4j.com/download/
    2. Create a new local DBMS, set a password, click Start.
    3. Confirm it is running: the DBMS shows 'Active' and Bolt is on port 7687.

  Option B - Docker
    docker run --name novatel-neo4j -p 7474:7474 -p 7687:7687 \\
      -e NEO4J_AUTH=neo4j/YourPassword -d neo4j:5

Then set the credentials and run the loader (PowerShell):

    $env:NEO4J_URI      = "bolt://localhost:7687"
    $env:NEO4J_USER     = "neo4j"
    $env:NEO4J_PASSWORD = "YourPassword"
    python -m knowledge_graph.graph_loader

Browse the result at http://localhost:7474 and try the queries in
knowledge_graph/cypher_queries.cypher.
""".strip()


class Neo4jUnavailable(RuntimeError):
    """Raised when the driver is missing or the server cannot be reached."""


def connection_settings() -> Dict[str, Optional[str]]:
    return {
        "uri": os.environ.get("NEO4J_URI", DEFAULT_URI),
        "user": os.environ.get("NEO4J_USER", DEFAULT_USER),
        "password": os.environ.get("NEO4J_PASSWORD"),
        "database": os.environ.get("NEO4J_DATABASE", DEFAULT_DATABASE),
    }


def _driver(settings: Dict[str, Optional[str]]):
    try:
        from neo4j import GraphDatabase
    except ImportError as error:  # driver not installed
        raise Neo4jUnavailable(
            "the neo4j Python driver is not installed (pip install neo4j)"
        ) from error

    if not settings["password"]:
        raise Neo4jUnavailable("NEO4J_PASSWORD is not set")

    try:
        driver = GraphDatabase.driver(
            settings["uri"],
            auth=(settings["user"], settings["password"]),
            connection_timeout=CONNECTION_TIMEOUT,
        )
        driver.verify_connectivity()
    except Exception as error:  # noqa: BLE001 - surfaced as one clear failure
        raise Neo4jUnavailable(f"cannot reach {settings['uri']}: {error}") from error
    return driver


def load_graph_payload(path: Path = GRAPH_JSON_PATH) -> Dict[str, Any]:
    """Read the built graph JSON produced by graph_builder."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the graph first: python -m knowledge_graph.graph_builder"
        )
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _batched(items: List[Dict[str, Any]], size: int = BATCH_SIZE) -> Iterable[List[Dict[str, Any]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _node_rows(nodes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group node rows by label, keyed on the graph node id."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for node in nodes:
        label = node["label"]
        if label not in ALLOWED_LABELS:
            raise ValueError(f"refusing to write unknown label {label!r}")
        properties = dict(node["properties"])
        properties["key"] = node["key"]
        grouped.setdefault(label, []).append({"id": node["id"], "props": properties})
    return grouped


def _edge_rows(edges: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group edge rows by relationship type."""
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
    """One uniqueness constraint per label on ``id`` - also the MERGE index."""
    for label in sorted(set(labels)):
        session.run(
            f"CREATE CONSTRAINT novatel_{label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )


def reset_graph(session) -> int:
    """Delete only the nodes this loader owns (and their relationships)."""
    deleted = 0
    for label in sorted(ALLOWED_LABELS):
        record = session.run(
            f"MATCH (n:{label}) WITH n LIMIT 100000 DETACH DELETE n RETURN count(n) AS deleted"
        ).single()
        deleted += record["deleted"] if record else 0
    return deleted


def load_into_neo4j(payload: Dict[str, Any], reset: bool = False) -> Dict[str, Any]:
    """MERGE every node and relationship into Neo4j and verify the result."""
    settings = connection_settings()
    driver = _driver(settings)
    nodes_by_label = _node_rows(payload["nodes"])
    edges_by_type = _edge_rows(payload["edges"])

    written_nodes = 0
    written_edges = 0
    try:
        with driver.session(database=settings["database"]) as session:
            ensure_constraints(session, nodes_by_label)
            if reset:
                removed = reset_graph(session)
                print(f"  reset: deleted {removed} pre-existing node(s)")

            for label, rows in sorted(nodes_by_label.items()):
                for batch in _batched(rows):
                    session.run(
                        f"UNWIND $rows AS row "
                        f"MERGE (n:{label} {{id: row.id}}) "
                        f"SET n += row.props",
                        rows=batch,
                    )
                written_nodes += len(rows)
                print(f"  merged {len(rows):>4} :{label}")

            for relationship, rows in sorted(edges_by_type.items()):
                for batch in _batched(rows):
                    session.run(
                        "UNWIND $rows AS row "
                        "MATCH (a {id: row.source}) "
                        "MATCH (b {id: row.target}) "
                        f"MERGE (a)-[r:{relationship}]->(b) "
                        "SET r += row.props",
                        rows=batch,
                    )
                written_edges += len(rows)
                print(f"  merged {len(rows):>4} -[:{relationship}]->")

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


def _counts(session) -> Dict[str, int]:
    """The verification query: how much is actually in the database."""
    nodes = session.run("MATCH (n) RETURN count(n) AS nodes").single()["nodes"]
    relationships = session.run(
        "MATCH ()-[r]->() RETURN count(r) AS relationships"
    ).single()["relationships"]
    return {"nodes": nodes, "relationships": relationships}


def fetch_counts() -> Optional[Dict[str, int]]:
    """Counts from Neo4j, or ``None`` when it is unavailable.

    Used by the evaluator, which must never fail because Neo4j is down.
    """
    try:
        settings = connection_settings()
        driver = _driver(settings)
    except Neo4jUnavailable:
        return None
    try:
        with driver.session(database=settings["database"]) as session:
            return _counts(session)
    except Exception:  # noqa: BLE001
        return None
    finally:
        driver.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Load the NovaTel graph into Neo4j.")
    parser.add_argument(
        "--verify", action="store_true", help="Only report Neo4j counts; write nothing."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing NovaTel nodes before loading (destructive).",
    )
    args = parser.parse_args()

    settings = connection_settings()
    print(f"target: {settings['uri']} (database {settings['database']}, user {settings['user']})")

    if args.verify:
        counts = fetch_counts()
        if counts is None:
            print("Neo4j not reachable.\n")
            print(STARTUP_HELP)
            return 2
        print(f"neo4j_nodes: {counts['nodes']}")
        print(f"neo4j_relationships: {counts['relationships']}")
        return 0

    payload = load_graph_payload()
    print(
        f"source: {GRAPH_JSON_PATH.name} "
        f"({len(payload['nodes'])} nodes, {len(payload['edges'])} edges)"
    )

    try:
        result = load_into_neo4j(payload, reset=args.reset)
    except Neo4jUnavailable as error:
        print(f"Neo4j not reachable: {error}\n", file=sys.stderr)
        print(STARTUP_HELP)
        return 2

    print("===== NEO4J LOAD VERIFICATION =====")
    print(f"merged_nodes: {result['written_nodes']}")
    print(f"merged_relationships: {result['written_edges']}")
    print(f"neo4j_nodes: {result['neo4j_nodes']}")
    print(f"neo4j_relationships: {result['neo4j_relationships']}")
    print("===================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
