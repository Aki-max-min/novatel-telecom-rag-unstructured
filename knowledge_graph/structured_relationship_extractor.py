"""Foreign-key edge extraction for the NovaTel STRUCTURED knowledge graph.

Every non-null foreign-key value in the 28 tables becomes one directed edge from
the child row to the parent row. The FK triples come from
``structured.schema.TABLE_SCHEMAS`` - nothing is hardcoded - and each triple is
mapped to a business relationship name (OF_CUSTOMER, ON_PLAN, PAYS_INVOICE, ...).

Every edge is checked against the parent table's real primary-key set, so
``fk_integrity_rate`` is measured, not asserted. A dangling FK is reported per
relationship rather than silently dropped.

Run standalone::

    python -m knowledge_graph.structured_relationship_extractor
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from knowledge_graph.structured_entity_extractor import (
    OUTPUT_DIR,
    TABLE_SCHEMAS,
    connect,
    entity_type,
    node_id,
)

#: (child table, fk column, parent table) -> relationship name.
#:
#: OF_CUSTOMER deliberately aggregates every table that points at
#: customer_master (14 of them), so "everything about this customer" is one
#: relationship type to traverse rather than fourteen.
RELATIONSHIP_NAMES: Dict[Tuple[str, str, str], str] = {
    ("subscriptions", "plan_id", "plan_master"): "ON_PLAN",
    ("recharge_transactions", "plan_id", "plan_master"): "FOR_PLAN",
    ("payment_transactions", "invoice_id", "invoices"): "PAYS_INVOICE",
    ("network_alarms", "site_id", "network_sites"): "AT_SITE",
    ("device_registry", "device_id", "device_config"): "OF_DEVICE_TYPE",
    ("escalation_cases", "ticket_id", "tickets"): "ESCALATES_TICKET",
}

#: Any FK that lands on customer_master is OF_CUSTOMER, whatever the child table.
CUSTOMER_TABLE = "customer_master"
CUSTOMER_RELATIONSHIP = "OF_CUSTOMER"

#: Printed in this order by the evaluator.
RELATIONSHIP_ORDER: Tuple[str, ...] = (
    "OF_CUSTOMER",
    "FOR_PLAN",
    "PAYS_INVOICE",
    "AT_SITE",
    "ON_PLAN",
    "OF_DEVICE_TYPE",
    "ESCALATES_TICKET",
)


def foreign_key_triples() -> List[Tuple[str, str, str]]:
    """Every (child table, fk column, parent table) declared in the schema."""
    triples: List[Tuple[str, str, str]] = []
    for table, schema in TABLE_SCHEMAS.items():
        for column, parent in (schema.get("foreign_keys") or {}).items():
            triples.append((table, column, parent))
    return sorted(triples)


def relationship_name(child: str, column: str, parent: str) -> str:
    """Business relationship name for an FK triple."""
    if parent == CUSTOMER_TABLE:
        return CUSTOMER_RELATIONSHIP
    try:
        return RELATIONSHIP_NAMES[(child, column, parent)]
    except KeyError as error:
        raise KeyError(
            f"FK {child}.{column} -> {parent} has no relationship name. Add it to "
            f"RELATIONSHIP_NAMES so the edge type is deliberate, not invented."
        ) from error


def _primary_key_set(parent: str, connection: sqlite3.Connection) -> set:
    """Real primary-key values of a parent table - the FK resolution target."""
    primary_key = TABLE_SCHEMAS[parent]["primary_key"]
    cursor = connection.execute(f'SELECT "{primary_key}" FROM "{parent}"')
    return {row[0] for row in cursor.fetchall()}


def extract_relationships(
    connection: sqlite3.Connection | None = None,
    triples: Iterable[Tuple[str, str, str]] | None = None,
) -> Dict[str, Any]:
    """One edge per non-null FK value, child -> parent, with an integrity check."""
    owned_connection = connection is None
    connection = connection or connect()
    triples = list(triples) if triples is not None else foreign_key_triples()

    edges: List[Dict[str, Any]] = []
    per_triple: List[Dict[str, Any]] = []
    dangling_examples: List[Dict[str, Any]] = []
    parent_keys: Dict[str, set] = {}

    total_values = 0
    total_null = 0
    total_dangling = 0

    try:
        for child, column, parent in triples:
            child_pk = TABLE_SCHEMAS[child]["primary_key"]
            child_entity = entity_type(child)
            parent_entity = entity_type(parent)
            name = relationship_name(child, column, parent)

            if parent not in parent_keys:
                parent_keys[parent] = _primary_key_set(parent, connection)
            valid = parent_keys[parent]

            cursor = connection.execute(
                f'SELECT "{child_pk}", "{column}" FROM "{child}" ORDER BY "{child_pk}"'
            )
            rows = cursor.fetchall()

            resolved = dangling = nulls = 0
            for child_key, fk_value in rows:
                if fk_value is None or fk_value == "":
                    nulls += 1
                    continue
                is_resolved = fk_value in valid
                if is_resolved:
                    resolved += 1
                else:
                    dangling += 1
                    if len(dangling_examples) < 20:
                        dangling_examples.append(
                            {
                                "relationship": name,
                                "child": f"{child}.{child_key}",
                                "column": column,
                                "unresolved_value": fk_value,
                                "parent_table": parent,
                            }
                        )
                edges.append(
                    {
                        "source": node_id(child_entity, child_key),
                        "target": node_id(parent_entity, fk_value),
                        "type": name,
                        "source_field": f"{child}.{column}",
                        "properties": {
                            "child_entity": child_entity,
                            "parent_entity": parent_entity,
                            "resolved": is_resolved,
                        },
                    }
                )

            total_values += resolved + dangling
            total_null += nulls
            total_dangling += dangling
            per_triple.append(
                {
                    "relationship": name,
                    "fk": f"{child}.{column} -> {parent}",
                    "child_entity": child_entity,
                    "parent_entity": parent_entity,
                    "rows": len(rows),
                    "fk_values": resolved + dangling,
                    "resolved": resolved,
                    "dangling": dangling,
                    "null": nulls,
                    "integrity_rate": round(
                        resolved / (resolved + dangling), 6
                    )
                    if (resolved + dangling)
                    else 1.0,
                }
            )
    finally:
        if owned_connection:
            connection.close()

    counts: Dict[str, int] = {}
    for edge in edges:
        counts[edge["type"]] = counts.get(edge["type"], 0) + 1

    integrity = (
        (total_values - total_dangling) / total_values if total_values else 1.0
    )
    stats = {
        "fk_triples": len(list(triples)),
        "total_fk_edges": len(edges),
        "fk_values_non_null": total_values,
        "fk_values_null": total_null,
        "resolved": total_values - total_dangling,
        "dangling": total_dangling,
        "fk_integrity_rate": round(integrity, 6),
        "edges_by_type": dict(sorted(counts.items())),
        "per_triple": per_triple,
    }
    return {"edges": edges, "stats": stats, "dangling_examples": dangling_examples}


def save_relationships(result: Dict[str, Any], output_dir: Path = OUTPUT_DIR) -> Path:
    """Write structured_edges.json (edges plus the integrity report)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "structured_edges.json"
    payload = {
        "stats": result["stats"],
        "dangling_examples": result["dangling_examples"],
        "edges": result["edges"],
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
    return path


def main() -> None:
    result = extract_relationships()
    path = save_relationships(result)
    stats = result["stats"]
    print(f"fk triples            : {stats['fk_triples']}")
    print(f"fk edges              : {stats['total_fk_edges']}")
    print(f"fk integrity rate     : {stats['fk_integrity_rate']}  dangling: {stats['dangling']}")
    print("per relationship:")
    for name, count in stats["edges_by_type"].items():
        print(f"  {name:<18}: {count}")
    print("per foreign key:")
    for row in stats["per_triple"]:
        print(
            f"  {row['fk']:<52} {row['relationship']:<18} "
            f"resolved={row['resolved']:<6} dangling={row['dangling']:<4} null={row['null']}"
        )
    if result["dangling_examples"]:
        print("dangling examples:")
        for example in result["dangling_examples"][:5]:
            print(f"  {example}")
    print(f"written               : {path}")


if __name__ == "__main__":
    main()
