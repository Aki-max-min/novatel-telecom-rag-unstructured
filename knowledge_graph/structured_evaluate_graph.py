"""Stats report for the NovaTel STRUCTURED knowledge graph.

Everything is read back off the built graph (``structured_graph.json``), not
recomputed from SQLite, so the report describes what was actually built. The
document KG's evaluator is untouched and still reports Phases 1-3 separately.

Usage::

    python -m knowledge_graph.structured_evaluate_graph
    python -m knowledge_graph.structured_evaluate_graph --skip-neo4j
    python -m knowledge_graph.structured_evaluate_graph --customer 1222
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from knowledge_graph.structured_graph_builder import INSTANCE_JSON_PATH
from knowledge_graph.structured_graph_queries import (
    customer_360,
    load_graph,
    sites_with_most_alarms,
    ticket_escalation_chains,
    top_hub_customers,
    widest_coverage_customer,
)
from knowledge_graph.structured_relationship_extractor import RELATIONSHIP_ORDER

#: Entity types shown on the spotcheck line, in report order.
SPOTCHECK_TYPES = (
    ("subscriptions", "Subscription"),
    ("invoices", "Invoice"),
    ("payments", "PaymentTransaction"),
    ("tickets", "Ticket"),
    ("kyc", "KYCRecord"),
)


def load_build_stats(path: Path = INSTANCE_JSON_PATH) -> Dict[str, Any]:
    """The stats block the builder wrote alongside the graph."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build it first: "
            f"python -m knowledge_graph.structured_graph_builder"
        )
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["stats"]


def neo4j_counts(skip: bool = False) -> Dict[str, Any]:
    """Live structured-graph counts, or 'not run' when Neo4j is unavailable."""
    if skip:
        return {"nodes": "not run", "relationships": "not run"}
    try:
        from knowledge_graph.structured_graph_loader import fetch_counts

        counts = fetch_counts()
    except Exception:  # noqa: BLE001 - Neo4j is optional
        counts = None
    if not counts:
        return {"nodes": "not run", "relationships": "not run"}
    return {"nodes": counts["nodes"], "relationships": counts["relationships"]}


def compute_report(
    graph, stats: Dict[str, Any], customer_id: Optional[str] = None
) -> Dict[str, Any]:
    entity_stats = stats["entity_extraction"]
    relationship_stats = stats["relationship_extraction"]

    nodes_by_type = entity_stats["nodes_by_type"]
    total_nodes = graph.number_of_nodes()
    total_edges = graph.number_of_edges()

    hubs = top_hub_customers(graph, limit=5)
    if customer_id is None:
        # The spotcheck subject is the customer touching the most distinct
        # entity types, not simply the highest-degree one - a customer can be
        # high-degree through a single table, which proves nothing about
        # multi-hop traversal.
        widest = widest_coverage_customer(graph)
        customer_id = widest["customer_id"] if widest else (
            hubs[0]["customer_id"] if hubs else ""
        )

    profile = customer_360(graph, customer_id)
    attached = profile.get("attached_counts", {}) if profile else {}
    spotcheck = {name: attached.get(entity, 0) for name, entity in SPOTCHECK_TYPES}

    return {
        "total_instance_nodes": total_nodes,
        "total_fk_edges": total_edges,
        "fk_integrity_rate": relationship_stats["fk_integrity_rate"],
        "dangling": relationship_stats["dangling"],
        "entity_types": entity_stats["entity_types"],
        "distinct_categories": entity_stats["distinct_categories"],
        "nodes_by_type": nodes_by_type,
        "nodes_by_type_sum": sum(nodes_by_type.values()),
        "edges_by_type": relationship_stats["edges_by_type"],
        "top5_hub_customers_by_degree": [
            f"{row['customer_id']}(deg={row['degree']})" for row in hubs
        ],
        "example_customer_id": customer_id,
        "spotcheck": spotcheck,
        "ticket_to_escalation_paths_in_graph": len(ticket_escalation_chains(graph)),
        "busiest_site": (sites_with_most_alarms(graph, limit=1) or [{}])[0],
    }


def print_block(report: Dict[str, Any], neo4j: Dict[str, Any]) -> None:
    print("===== NOVATEL STRUCTURED KG — PHASE 4 STATS =====")
    print(f"total_instance_nodes: {report['total_instance_nodes']}")
    print(f"total_fk_edges: {report['total_fk_edges']}")
    print(
        f"fk_integrity_rate: {report['fk_integrity_rate']}   "
        f"dangling: {report['dangling']}"
    )
    print(f"entity_types: {report['entity_types']}")
    print(f"distinct_categories: {report['distinct_categories']}")
    print("nodes_by_type:")
    for entity, count in report["nodes_by_type"].items():
        print(f"  {entity}: {count}")
    print("edges_by_type:")
    for name in RELATIONSHIP_ORDER:
        print(f"  {name}: {report['edges_by_type'].get(name, 0)}")
    print(f"top5_hub_customers_by_degree: {report['top5_hub_customers_by_degree']}")
    print("--- multi-hop spotcheck ---")
    print(f"example_customer_id: {report['example_customer_id']}")
    spotcheck = report["spotcheck"]
    print(
        f"  subscriptions: {spotcheck['subscriptions']}  "
        f"invoices: {spotcheck['invoices']}  "
        f"payments: {spotcheck['payments']}  "
        f"tickets: {spotcheck['tickets']}  "
        f"kyc: {spotcheck['kyc']}"
    )
    print(
        f"  ticket_to_escalation_paths_in_graph: "
        f"{report['ticket_to_escalation_paths_in_graph']}"
    )
    print("--- neo4j ---")
    print(f"neo4j_nodes: {neo4j['nodes']}")
    print(f"neo4j_relationships: {neo4j['relationships']}")
    print("=======================================")


def print_notes(report: Dict[str, Any]) -> None:
    print()
    print("notes:")
    total = report["total_instance_nodes"]
    summed = report["nodes_by_type_sum"]
    verdict = "OK" if summed == total else "MISMATCH"
    print(
        f"  nodes_by_type sums to {summed} against total_instance_nodes {total} [{verdict}] "
        f"across {len(report['nodes_by_type'])} entity types."
    )
    print(
        "  fk_integrity_rate is measured, not asserted: every FK value is checked against the "
        "parent table's real primary-key set before the edge is written."
    )
    print(
        "  ticket_to_escalation_paths_in_graph is graph-wide (every "
        "EscalationCase -> Ticket -> Customer chain), not just the example customer."
    )
    site = report.get("busiest_site") or {}
    if site:
        print(
            f"  busiest site: {site.get('site_id')} with {site.get('alarms')} alarms "
            f"{site.get('by_severity')}"
        )
    print(
        "  neo4j counts are scoped to the :StructuredEntity label, so the document KG "
        "(Phases 1-3) is never mixed into them."
    )


def _force_utf8_stdout() -> None:
    """The block header contains an em dash; Windows consoles default to cp1252."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main() -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Evaluate the structured knowledge graph.")
    parser.add_argument("--skip-neo4j", action="store_true", help="Report Neo4j counts as 'not run'.")
    parser.add_argument("--customer", default=None, help="customer_id for the spotcheck.")
    args = parser.parse_args()

    try:
        stats = load_build_stats()
        graph = load_graph()
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1

    report = compute_report(graph, stats, args.customer)
    print_block(report, neo4j_counts(args.skip_neo4j))
    print_notes(report)

    if report["nodes_by_type_sum"] != report["total_instance_nodes"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
