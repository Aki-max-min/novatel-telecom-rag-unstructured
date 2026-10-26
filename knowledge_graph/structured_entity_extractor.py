"""Instance-node extraction for the NovaTel STRUCTURED knowledge graph.

Reads every row of the 28 SQL tables and emits one graph node per row. The
schema is never hardcoded: ``structured.schema.TABLE_SCHEMAS`` is imported and
used as the source of truth for primary keys, foreign keys and category tags.

Node id is ``f"{EntityType}:{primary_key_value}"`` - a single colon, which keeps
these ids distinct from the document KG's ``Label::key`` form, so the two graphs
can never collide if they are ever loaded side by side.

This module writes only ``knowledge_graph/output/structured_*.json``; nothing
belonging to the document KG (Phases 1-3) is touched.

Run standalone::

    python -m knowledge_graph.structured_entity_extractor
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from structured.schema import TABLE_SCHEMAS  # noqa: E402  (path set above)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
DATABASE_PATH = REPO_ROOT / "data" / "processed" / "structured" / "novatel_structured.db"
CSV_DIR = REPO_ROOT / "data" / "raw" / "structured"

#: table -> EntityType.
#:
#: The rule: strip a ``_master`` suffix, singularise a plural table name, then
#: PascalCase. Telecom acronyms stay uppercase (CDR, SIM, ESIM, KYC, OTT, VAS,
#: 5G) because "Cdr" and "Kyc" read as typos in a graph browser. The mapping is
#: written out in full rather than computed, so what each table becomes is
#: reviewable at a glance and cannot drift with a change to the derivation.
ENTITY_TYPES: Dict[str, str] = {
    "customer_master": "Customer",
    "plan_master": "Plan",
    "subscriptions": "Subscription",
    "recharge_transactions": "RechargeTransaction",
    "invoices": "Invoice",
    "payment_transactions": "PaymentTransaction",
    "sim_inventory": "SIMInventory",
    "esim_profiles": "ESIMProfile",
    "network_sites": "NetworkSite",
    "network_alarms": "NetworkAlarm",
    "tickets": "Ticket",
    "cdr": "CDR",
    "roaming_usage": "RoamingUsage",
    "kyc_records": "KYCRecord",
    "porting_requests": "PortingRequest",
    "orders": "Order",
    "corporate_accounts": "CorporateAccount",
    "device_config": "DeviceConfig",
    "device_registry": "DeviceRegistry",
    "retail_outlets": "RetailOutlet",
    "technicians": "Technician",
    "ott_subscriptions": "OTTSubscription",
    "offers": "Offer",
    "fraud_cases": "FraudCase",
    "vas_subscriptions": "VASSubscription",
    "coverage_5g": "Coverage5G",
    "fiber_inventory": "FiberInventory",
    "escalation_cases": "EscalationCase",
}

#: Column names always kept as node properties when the table has them.
PREFERRED_COLUMNS: Tuple[str, ...] = (
    "status",
    "msisdn",
    "name",
    "severity",
    "level",
    "category",
    "subcategory",
    "circle",
    "city",
    "region",
    "country",
    "technology",
    "brand",
    "model",
    "skill",
    "segment",
    "price",
    "amount",
    "duration_sec",
    "speed_mbps",
    "coverage_percent",
    "discount_percent",
    "timestamp",
)

#: Column-name suffixes kept as node properties (status/type/name/date/amount).
PREFERRED_SUFFIXES: Tuple[str, ...] = (
    "_status",
    "_type",
    "_name",
    "_date",
    "_at",
    "_amount",
    "_time",
)

#: Cap on non-key properties per node, so nodes stay readable in a browser.
MAX_PROPERTIES = 6


def entity_type(table: str) -> str:
    """EntityType for a table name."""
    try:
        return ENTITY_TYPES[table]
    except KeyError as error:
        raise KeyError(
            f"table {table!r} has no EntityType mapping in ENTITY_TYPES"
        ) from error


def node_id(entity: str, key: Any) -> str:
    """``EntityType:primary_key`` - single colon, distinct from the document KG."""
    return f"{entity}:{key}"


def selected_columns(table: str) -> List[str]:
    """The 'few meaningful columns' kept as properties for one table.

    Deterministic: primary key first, then columns matching the preference list
    in the table's own declared column order, capped at ``MAX_PROPERTIES``.
    Foreign-key columns are skipped - they become edges, and repeating them as
    properties would double-store the same fact.
    """
    schema = TABLE_SCHEMAS[table]
    primary_key = schema["primary_key"]
    foreign_keys = set((schema.get("foreign_keys") or {}).keys())

    chosen: List[str] = []
    for column in schema["columns"]:
        if column == primary_key or column in foreign_keys:
            continue
        if column in PREFERRED_COLUMNS or column.endswith(PREFERRED_SUFFIXES):
            chosen.append(column)
        if len(chosen) >= MAX_PROPERTIES:
            break
    return [primary_key] + chosen


def _coerce(value: Any) -> Any:
    """SQLite values are already scalars; normalise None and bytes for JSON."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def load_rows(
    table: str, connection: sqlite3.Connection
) -> List[Dict[str, Any]]:
    """Every row of a table, ordered by primary key for reproducibility."""
    primary_key = TABLE_SCHEMAS[table]["primary_key"]
    columns = selected_columns(table)
    quoted = ", ".join(f'"{column}"' for column in columns)
    cursor = connection.execute(
        f'SELECT {quoted} FROM "{table}" ORDER BY "{primary_key}"'
    )
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def connect(database_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    if not database_path.exists():
        raise FileNotFoundError(
            f"{database_path} not found. The structured KG reads the SQLite build "
            f"produced by Person A's structured pipeline."
        )
    return sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)


def extract_instance_nodes(
    connection: sqlite3.Connection | None = None,
    tables: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """One node per row across every table.

    Returns ``nodes`` (ordered by entity type, then primary key) and ``stats``.
    """
    owned_connection = connection is None
    connection = connection or connect()
    tables = list(tables) if tables is not None else list(TABLE_SCHEMAS)

    nodes: List[Dict[str, Any]] = []
    try:
        for table in sorted(tables):
            schema = TABLE_SCHEMAS[table]
            entity = entity_type(table)
            primary_key = schema["primary_key"]
            category = schema.get("category_tag", "")

            for row in load_rows(table, connection):
                key = row[primary_key]
                # The schema tag is written as `category_tag`, never `category`:
                # `tickets` has its own `category` column (Network, Billing, ...)
                # which would otherwise overwrite the schema tag on 1,486 nodes.
                properties = {
                    "entity_type": entity,
                    "category_tag": category,
                    "source_table": table,
                    "primary_key": primary_key,
                    primary_key: _coerce(key),
                }
                for column, value in row.items():
                    if column != primary_key:
                        properties[column] = _coerce(value)
                nodes.append(
                    {
                        "id": node_id(entity, key),
                        "entity_type": entity,
                        "key": key,
                        "category_tag": category,
                        "properties": properties,
                    }
                )
    finally:
        if owned_connection:
            connection.close()

    counts: Dict[str, int] = {}
    for node in nodes:
        counts[node["entity_type"]] = counts.get(node["entity_type"], 0) + 1

    unique_ids = {node["id"] for node in nodes}
    if len(unique_ids) != len(nodes):
        raise ValueError(
            f"node id collision: {len(nodes)} rows produced {len(unique_ids)} ids"
        )

    stats = {
        "tables_read": len(tables),
        "total_instance_nodes": len(nodes),
        "entity_types": len(counts),
        "distinct_categories": len(
            {schema.get("category_tag", "") for schema in TABLE_SCHEMAS.values()}
        ),
        "nodes_by_type": dict(sorted(counts.items())),
        "duplicate_node_ids": len(nodes) - len(unique_ids),
    }
    return {"nodes": nodes, "stats": stats}


def save_instance_nodes(result: Dict[str, Any], output_dir: Path = OUTPUT_DIR) -> Path:
    """Write structured_nodes.json (nodes plus extraction stats)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "structured_nodes.json"
    payload = {"stats": result["stats"], "nodes": result["nodes"]}
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
    return path


def main() -> None:
    result = extract_instance_nodes()
    path = save_instance_nodes(result)
    stats = result["stats"]
    print(f"tables read           : {stats['tables_read']}")
    print(f"instance nodes        : {stats['total_instance_nodes']}")
    print(f"entity types          : {stats['entity_types']}")
    print(f"distinct categories   : {stats['distinct_categories']}")
    for entity, count in stats["nodes_by_type"].items():
        print(f"  {entity:<22}: {count}")
    print(f"written               : {path}")


if __name__ == "__main__":
    main()
