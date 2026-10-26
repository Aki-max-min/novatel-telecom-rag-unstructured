"""Builds the NovaTel STRUCTURED knowledge graph (instance + schema views).

Two distinct graphs are produced and kept in separate files:

* **Instance graph** - one node per database row (43,928) and one edge per
  non-null foreign key (31,027). This is the graph you query for "everything
  about customer X".
* **Schema / ontology graph** - 28 EntityType nodes, 20 FK relationship-type
  edges, 24 Category nodes and the EntityType -> Category edges. This is the map
  of the database, not the data in it.

Outputs (all prefixed ``structured_``, so nothing from the document KG is
touched):

| File | Contents |
|---|---|
| ``structured_kg.graphml`` | instance graph |
| ``structured_nodes.json`` | instance nodes + extraction stats |
| ``structured_edges.json`` | FK edges + integrity report |
| ``structured_graph.json`` | instance nodes + edges + all stats in one file |
| ``structured_schema_kg.graphml`` | schema graph |
| ``structured_schema_graph.json`` | schema nodes + edges |

Usage::

    python -m knowledge_graph.structured_graph_builder
    python -m knowledge_graph.structured_graph_builder --skip-graphml   # JSON only
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import networkx as nx

from knowledge_graph.structured_entity_extractor import (
    ENTITY_TYPES,
    OUTPUT_DIR,
    TABLE_SCHEMAS,
    connect,
    entity_type,
    extract_instance_nodes,
    save_instance_nodes,
)
from knowledge_graph.structured_relationship_extractor import (
    RELATIONSHIP_ORDER,
    extract_relationships,
    foreign_key_triples,
    relationship_name,
    save_relationships,
)

INSTANCE_GRAPHML_PATH = OUTPUT_DIR / "structured_kg.graphml"
INSTANCE_JSON_PATH = OUTPUT_DIR / "structured_graph.json"
SCHEMA_GRAPHML_PATH = OUTPUT_DIR / "structured_schema_kg.graphml"
SCHEMA_JSON_PATH = OUTPUT_DIR / "structured_schema_graph.json"


def _graphml_safe(value: Any) -> Any:
    """GraphML carries scalars only; render anything else as a string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


# ---------------------------------------------------------------------------
# Instance graph
# ---------------------------------------------------------------------------
def build_instance_graph(
    entities: Dict[str, Any], relationships: Dict[str, Any]
) -> nx.MultiDiGraph:
    """One node per row, one edge per foreign key, child -> parent."""
    graph = nx.MultiDiGraph()
    graph.graph["name"] = "NovaTel Structured KG - instance graph"
    graph.graph["view"] = "instance"
    graph.graph["schema_version"] = "1.0.0"

    for node in entities["nodes"]:
        attributes = {name: _graphml_safe(value) for name, value in node["properties"].items()}
        graph.add_node(node["id"], **attributes)

    known = set(graph.nodes)
    missing = [
        edge
        for edge in relationships["edges"]
        if edge["source"] not in known or edge["target"] not in known
    ]
    if missing:
        raise ValueError(
            f"{len(missing)} FK edge(s) reference rows absent from the node set, "
            f"first: {missing[0]}. With fk_integrity_rate 1.0 this must be empty."
        )

    for edge in relationships["edges"]:
        attributes = {"type": edge["type"], "source_field": edge["source_field"]}
        for name, value in edge.get("properties", {}).items():
            attributes[name] = _graphml_safe(value)
        graph.add_edge(edge["source"], edge["target"], key=edge["type"], **attributes)

    if graph.number_of_edges() != len(relationships["edges"]):
        raise ValueError(
            f"edge collapse detected: extracted {len(relationships['edges'])} edges "
            f"but the graph holds {graph.number_of_edges()}"
        )
    return graph


# ---------------------------------------------------------------------------
# Schema / ontology graph
# ---------------------------------------------------------------------------
def build_schema_graph() -> Dict[str, Any]:
    """The map of the database: EntityTypes, FK relationship types, Categories.

    Built from TABLE_SCHEMAS alone - it needs no data, only the schema, so it
    stays valid even if the database is empty.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    for table in sorted(TABLE_SCHEMAS):
        schema = TABLE_SCHEMAS[table]
        entity = entity_type(table)
        nodes.append(
            {
                "id": f"EntityType:{entity}",
                "label": "EntityType",
                "key": entity,
                "properties": {
                    "label": "EntityType",
                    "entity_type": entity,
                    "source_table": table,
                    "primary_key": schema["primary_key"],
                    "category_tag": schema.get("category_tag", ""),
                    "column_count": len(schema["columns"]),
                    "foreign_key_count": len(schema.get("foreign_keys") or {}),
                },
            }
        )

    categories = sorted({schema.get("category_tag", "") for schema in TABLE_SCHEMAS.values()})
    for category in categories:
        tables = sorted(
            table
            for table, schema in TABLE_SCHEMAS.items()
            if schema.get("category_tag", "") == category
        )
        nodes.append(
            {
                "id": f"StructuredCategory:{category}",
                "label": "StructuredCategory",
                "key": category,
                "properties": {
                    "label": "StructuredCategory",
                    "code": category,
                    "branch": "structured",
                    "table_count": len(tables),
                    "tables": ", ".join(tables),
                    "warning": (
                        "Structured category codes are NOT the document branch's codes. "
                        "Never join the two branches on this code."
                    ),
                },
            }
        )

    # EntityType -> StructuredCategory
    for table in sorted(TABLE_SCHEMAS):
        entity = entity_type(table)
        category = TABLE_SCHEMAS[table].get("category_tag", "")
        edges.append(
            {
                "source": f"EntityType:{entity}",
                "target": f"StructuredCategory:{category}",
                "type": "IN_CATEGORY",
                "source_field": "schema.category_tag",
                "properties": {"branch": "structured"},
            }
        )

    # EntityType -> EntityType, one per declared FK triple.
    for child, column, parent in foreign_key_triples():
        edges.append(
            {
                "source": f"EntityType:{entity_type(child)}",
                "target": f"EntityType:{entity_type(parent)}",
                "type": relationship_name(child, column, parent),
                "source_field": f"{child}.{column} -> {parent}",
                "properties": {
                    "fk_column": column,
                    "child_table": child,
                    "parent_table": parent,
                },
            }
        )

    stats = {
        "entity_type_nodes": len(TABLE_SCHEMAS),
        "category_nodes": len(categories),
        "total_nodes": len(nodes),
        "fk_relationship_edges": len(foreign_key_triples()),
        "category_edges": len(TABLE_SCHEMAS),
        "total_edges": len(edges),
        "relationship_types": sorted({edge["type"] for edge in edges if edge["type"] != "IN_CATEGORY"}),
    }
    return {"nodes": nodes, "edges": edges, "stats": stats}


def build_schema_networkx(schema_graph: Dict[str, Any]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.graph["name"] = "NovaTel Structured KG - schema graph"
    graph.graph["view"] = "schema"
    for node in schema_graph["nodes"]:
        graph.add_node(
            node["id"],
            **{name: _graphml_safe(value) for name, value in node["properties"].items()},
        )
    for edge in schema_graph["edges"]:
        attributes = {"type": edge["type"], "source_field": edge["source_field"]}
        for name, value in edge.get("properties", {}).items():
            attributes[name] = _graphml_safe(value)
        # Keyed on the FK itself so two FKs between the same pair stay separate.
        graph.add_edge(
            edge["source"], edge["target"], key=edge["source_field"], **attributes
        )
    if graph.number_of_edges() != len(schema_graph["edges"]):
        raise ValueError("schema graph edge collapse detected")
    return graph


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def save_all(
    instance_graph: nx.MultiDiGraph,
    schema_networkx: nx.MultiDiGraph,
    entities: Dict[str, Any],
    relationships: Dict[str, Any],
    schema_graph: Dict[str, Any],
    output_dir: Path = OUTPUT_DIR,
    skip_graphml: bool = False,
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {
        "nodes_json": save_instance_nodes(entities, output_dir),
        "edges_json": save_relationships(relationships, output_dir),
    }

    instance_json = output_dir / INSTANCE_JSON_PATH.name
    with instance_json.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "graph": dict(instance_graph.graph),
                "stats": {
                    "entity_extraction": entities["stats"],
                    "relationship_extraction": {
                        key: value
                        for key, value in relationships["stats"].items()
                        if key != "per_triple"
                    },
                    "per_foreign_key": relationships["stats"]["per_triple"],
                    "graph": {
                        "total_nodes": instance_graph.number_of_nodes(),
                        "total_edges": instance_graph.number_of_edges(),
                    },
                },
                "nodes": entities["nodes"],
                "edges": relationships["edges"],
            },
            handle,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    written["graph_json"] = instance_json

    schema_json = output_dir / SCHEMA_JSON_PATH.name
    with schema_json.open("w", encoding="utf-8") as handle:
        json.dump(schema_graph, handle, indent=2, ensure_ascii=False, default=str)
    written["schema_json"] = schema_json

    if not skip_graphml:
        instance_graphml = output_dir / INSTANCE_GRAPHML_PATH.name
        nx.write_graphml(instance_graph, instance_graphml)
        written["graphml"] = instance_graphml

        schema_graphml = output_dir / SCHEMA_GRAPHML_PATH.name
        nx.write_graphml(schema_networkx, schema_graphml)
        written["schema_graphml"] = schema_graphml

    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the NovaTel structured knowledge graph."
    )
    parser.add_argument(
        "--skip-graphml",
        action="store_true",
        help="Write the JSON views only (faster; skips the 43,928-node graphml).",
    )
    args = parser.parse_args()

    connection = connect()
    try:
        entities = extract_instance_nodes(connection)
        relationships = extract_relationships(connection)
    finally:
        connection.close()

    instance_graph = build_instance_graph(entities, relationships)
    schema_graph = build_schema_graph()
    schema_networkx = build_schema_networkx(schema_graph)
    written = save_all(
        instance_graph,
        schema_networkx,
        entities,
        relationships,
        schema_graph,
        skip_graphml=args.skip_graphml,
    )

    entity_stats = entities["stats"]
    relationship_stats = relationships["stats"]

    print("===== NOVATEL STRUCTURED KG - BUILD =====")
    print(f"tables read        : {entity_stats['tables_read']}")
    print(f"instance nodes     : {instance_graph.number_of_nodes()}")
    print(f"fk edges           : {instance_graph.number_of_edges()}")
    print(
        f"fk integrity       : {relationship_stats['fk_integrity_rate']} "
        f"(dangling {relationship_stats['dangling']})"
    )
    print(f"entity types       : {entity_stats['entity_types']}")
    print(f"categories         : {entity_stats['distinct_categories']}")
    for name in RELATIONSHIP_ORDER:
        print(f"  edge {name:<18}: {relationship_stats['edges_by_type'].get(name, 0)}")
    print(
        "schema graph       : "
        f"{schema_graph['stats']['total_nodes']} nodes "
        f"({schema_graph['stats']['entity_type_nodes']} EntityType + "
        f"{schema_graph['stats']['category_nodes']} Category), "
        f"{schema_graph['stats']['total_edges']} edges "
        f"({schema_graph['stats']['fk_relationship_edges']} FK + "
        f"{schema_graph['stats']['category_edges']} IN_CATEGORY)"
    )
    print("written:")
    for name, path in written.items():
        print(f"  {name:<15}: {path}")
    print("=" * 42)


if __name__ == "__main__":
    main()
