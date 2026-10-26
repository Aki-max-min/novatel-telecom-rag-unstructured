"""Multi-hop queries over the NovaTel STRUCTURED instance graph.

These are the questions the structured KG exists to answer - the ones that would
otherwise be a stack of SQL joins. Each takes the loaded graph and returns plain
Python values.

The graph is loaded from ``structured_graph.json`` rather than the graphml: same
data, but parsing 43,928 nodes from JSON is several times faster than from XML.

Usage::

    python -m knowledge_graph.structured_graph_queries
    python -m knowledge_graph.structured_graph_queries --customer 1169
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from knowledge_graph.structured_graph_builder import INSTANCE_JSON_PATH

CUSTOMER = "Customer"
TICKET = "Ticket"
INVOICE = "Invoice"
PAYMENT = "PaymentTransaction"
ESCALATION = "EscalationCase"
SITE = "NetworkSite"
ALARM = "NetworkAlarm"

#: Entity types shown in the customer-360 view, in report order.
CUSTOMER_360_TYPES: Tuple[str, ...] = (
    "Subscription",
    "Invoice",
    "PaymentTransaction",
    "Ticket",
    "KYCRecord",
    "DeviceRegistry",
    "ESIMProfile",
    "OTTSubscription",
    "VASSubscription",
    "RoamingUsage",
    "Order",
    "PortingRequest",
    "FraudCase",
    "FiberInventory",
)

SUCCESSFUL_PAYMENT_STATUS = "SUCCESS"


def load_graph(path: Path = INSTANCE_JSON_PATH) -> nx.MultiDiGraph:
    """Rebuild the instance graph from the builder's JSON output."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build it first: "
            f"python -m knowledge_graph.structured_graph_builder"
        )
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    graph = nx.MultiDiGraph()
    for node in payload["nodes"]:
        graph.add_node(node["id"], **node["properties"])
    for edge in payload["edges"]:
        graph.add_edge(
            edge["source"],
            edge["target"],
            key=edge["type"],
            type=edge["type"],
            source_field=edge["source_field"],
            **edge.get("properties", {}),
        )
    return graph


def node_id(entity: str, key: Any) -> str:
    return f"{entity}:{key}"


def _children(graph: nx.MultiDiGraph, parent: str, relationship: str) -> List[str]:
    """Rows pointing AT this node over the given relationship (child -> parent)."""
    return [
        source
        for source, _, attributes in graph.in_edges(parent, data=True)
        if attributes.get("type") == relationship
    ]


def _parents(graph: nx.MultiDiGraph, child: str, relationship: str) -> List[str]:
    return [
        target
        for _, target, attributes in graph.out_edges(child, data=True)
        if attributes.get("type") == relationship
    ]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# 1. All tickets for a customer
# ---------------------------------------------------------------------------
def tickets_for_customer(graph: nx.MultiDiGraph, customer_id: Any) -> List[Dict[str, Any]]:
    """Every ticket raised by one customer (Customer <- Ticket, one hop)."""
    customer = node_id(CUSTOMER, customer_id)
    if customer not in graph:
        return []
    rows = []
    for child in _children(graph, customer, "OF_CUSTOMER"):
        attributes = graph.nodes[child]
        if attributes.get("entity_type") != TICKET:
            continue
        rows.append(
            {
                "ticket_id": attributes.get("ticket_id", child.split(":", 1)[-1]),
                "status": attributes.get("status", ""),
                "category": attributes.get("category", ""),
                "subcategory": attributes.get("subcategory", ""),
                "created_at": attributes.get("created_at", ""),
            }
        )
    return sorted(rows, key=lambda row: str(row["ticket_id"]))


# ---------------------------------------------------------------------------
# 2. Customer 360
# ---------------------------------------------------------------------------
def customer_360(graph: nx.MultiDiGraph, customer_id: Any) -> Dict[str, Any]:
    """Everything attached to one customer, grouped by entity type.

    One hop over OF_CUSTOMER covers 14 tables at once - that is the payoff of
    aggregating all customer FKs into a single relationship type.
    """
    customer = node_id(CUSTOMER, customer_id)
    if customer not in graph:
        return {}

    attached: Dict[str, List[str]] = defaultdict(list)
    for child in _children(graph, customer, "OF_CUSTOMER"):
        attached[graph.nodes[child].get("entity_type", "?")].append(child)

    profile = graph.nodes[customer]
    counts = {
        name: len(attached.get(name, []))
        for name in CUSTOMER_360_TYPES
        if attached.get(name)
    }
    return {
        "customer_id": customer_id,
        "msisdn": profile.get("msisdn", ""),
        "name": profile.get("name", ""),
        "status": profile.get("status", ""),
        "account_type": profile.get("account_type", ""),
        "kyc_status": profile.get("kyc_status", ""),
        "attached_counts": counts,
        "attached_total": sum(len(values) for values in attached.values()),
        "attached_ids": {name: sorted(values) for name, values in attached.items()},
    }


# ---------------------------------------------------------------------------
# 3. Ticket -> Escalation chains
# ---------------------------------------------------------------------------
def ticket_escalation_chains(
    graph: nx.MultiDiGraph, limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Two-hop chains Customer <- Ticket <- EscalationCase.

    Answers "which complaints escalated, and whose", which in SQL is a
    three-table join.
    """
    chains: List[Dict[str, Any]] = []
    for node, attributes in graph.nodes(data=True):
        if attributes.get("entity_type") != ESCALATION:
            continue
        tickets = _parents(graph, node, "ESCALATES_TICKET")
        for ticket in tickets:
            ticket_attributes = graph.nodes[ticket]
            customers = _parents(graph, ticket, "OF_CUSTOMER")
            customer = customers[0] if customers else ""
            chains.append(
                {
                    "escalation_id": attributes.get("escalation_id", node.split(":", 1)[-1]),
                    "level": attributes.get("level", ""),
                    "escalation_status": attributes.get("status", ""),
                    "escalated_at": attributes.get("escalated_at", ""),
                    "ticket_id": ticket_attributes.get("ticket_id", ticket.split(":", 1)[-1]),
                    "ticket_status": ticket_attributes.get("status", ""),
                    "ticket_category": ticket_attributes.get("category", ""),
                    "customer_id": graph.nodes[customer].get("customer_id", "") if customer else "",
                }
            )
    chains.sort(key=lambda row: str(row["escalation_id"]))
    return chains[:limit] if limit else chains


# ---------------------------------------------------------------------------
# 4. Invoice -> Payment reconciliation for a customer
# ---------------------------------------------------------------------------
def invoice_payment_reconciliation(
    graph: nx.MultiDiGraph, customer_id: Any
) -> Dict[str, Any]:
    """Per-invoice billed vs paid, walking Customer <- Invoice <- PaymentTransaction.

    Only ``SUCCESS`` payments count towards the paid total; FAILED and PENDING
    attempts are counted separately rather than silently treated as payment.
    """
    customer = node_id(CUSTOMER, customer_id)
    if customer not in graph:
        return {}

    invoices = [
        child
        for child in _children(graph, customer, "OF_CUSTOMER")
        if graph.nodes[child].get("entity_type") == INVOICE
    ]

    rows: List[Dict[str, Any]] = []
    for invoice in sorted(invoices):
        invoice_attributes = graph.nodes[invoice]
        billed = _as_float(invoice_attributes.get("total_amount"))
        paid = 0.0
        attempts = Counter()
        for payment in _children(graph, invoice, "PAYS_INVOICE"):
            payment_attributes = graph.nodes[payment]
            status = str(payment_attributes.get("status", ""))
            attempts[status] += 1
            if status == SUCCESSFUL_PAYMENT_STATUS:
                paid += _as_float(payment_attributes.get("amount"))
        rows.append(
            {
                "invoice_id": invoice_attributes.get("invoice_id", invoice.split(":", 1)[-1]),
                "payment_status_field": invoice_attributes.get("payment_status", ""),
                "billed": round(billed, 2),
                "paid_success": round(paid, 2),
                "balance": round(billed - paid, 2),
                "payment_attempts": dict(sorted(attempts.items())),
            }
        )

    return {
        "customer_id": customer_id,
        "invoices": len(rows),
        "total_billed": round(sum(row["billed"] for row in rows), 2),
        "total_paid_success": round(sum(row["paid_success"] for row in rows), 2),
        "total_balance": round(sum(row["balance"] for row in rows), 2),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 5. Sites with the most alarms
# ---------------------------------------------------------------------------
def sites_with_most_alarms(
    graph: nx.MultiDiGraph, limit: int = 10
) -> List[Dict[str, Any]]:
    """Alarm load per site, with a severity breakdown (NetworkSite <- NetworkAlarm)."""
    rows: List[Dict[str, Any]] = []
    for node, attributes in graph.nodes(data=True):
        if attributes.get("entity_type") != SITE:
            continue
        alarms = _children(graph, node, "AT_SITE")
        if not alarms:
            continue
        severities = Counter(
            str(graph.nodes[alarm].get("severity", "")) for alarm in alarms
        )
        rows.append(
            {
                "site_id": attributes.get("site_id", node.split(":", 1)[-1]),
                "technology": attributes.get("technology", ""),
                "site_status": attributes.get("status", ""),
                "alarms": len(alarms),
                "by_severity": dict(sorted(severities.items())),
            }
        )
    rows.sort(key=lambda row: (-row["alarms"], str(row["site_id"])))
    return rows[:limit]


# ---------------------------------------------------------------------------
# 6. Highest-degree customers
# ---------------------------------------------------------------------------
def top_hub_customers(graph: nx.MultiDiGraph, limit: int = 5) -> List[Dict[str, Any]]:
    """Customers with the most attached rows - the busiest accounts in the graph."""
    rows = []
    for node, attributes in graph.nodes(data=True):
        if attributes.get("entity_type") != CUSTOMER:
            continue
        rows.append(
            {
                "customer_id": attributes.get("customer_id", node.split(":", 1)[-1]),
                "degree": graph.degree(node),
                "msisdn": attributes.get("msisdn", ""),
                "account_type": attributes.get("account_type", ""),
                "status": attributes.get("status", ""),
            }
        )
    rows.sort(key=lambda row: (-row["degree"], str(row["customer_id"])))
    return rows[:limit]


def widest_coverage_customer(graph: nx.MultiDiGraph) -> Optional[Dict[str, Any]]:
    """The customer attached to the most distinct entity types.

    Used as the default spotcheck subject: the highest-degree customer can be
    high-degree through one table alone, which demonstrates nothing about
    multi-hop traversal. Deterministic - ties break on degree, then customer_id.
    """
    best: Optional[Dict[str, Any]] = None
    for node, attributes in graph.nodes(data=True):
        if attributes.get("entity_type") != CUSTOMER:
            continue
        types = {
            graph.nodes[child].get("entity_type")
            for child in _children(graph, node, "OF_CUSTOMER")
        }
        candidate = {
            "customer_id": attributes.get("customer_id", node.split(":", 1)[-1]),
            "distinct_types": len(types),
            "degree": graph.degree(node),
        }
        key = (
            candidate["distinct_types"],
            candidate["degree"],
            [-ord(character) for character in str(candidate["customer_id"])],
        )
        if best is None or key > best["_key"]:
            candidate["_key"] = key
            best = candidate
    if best:
        best.pop("_key", None)
    return best


# ---------------------------------------------------------------------------
# 7. Plan adoption (subscriptions + recharges per plan)
# ---------------------------------------------------------------------------
def plan_adoption(graph: nx.MultiDiGraph, limit: int = 10) -> List[Dict[str, Any]]:
    """Subscriptions and recharges attached to each plan (Plan <- ON_PLAN/FOR_PLAN)."""
    rows = []
    for node, attributes in graph.nodes(data=True):
        if attributes.get("entity_type") != "Plan":
            continue
        subscriptions = len(_children(graph, node, "ON_PLAN"))
        recharges = len(_children(graph, node, "FOR_PLAN"))
        rows.append(
            {
                "plan_id": attributes.get("plan_id", node.split(":", 1)[-1]),
                "plan_name": attributes.get("plan_name", ""),
                "price": attributes.get("price", ""),
                "subscriptions": subscriptions,
                "recharges": recharges,
                "total": subscriptions + recharges,
            }
        )
    rows.sort(key=lambda row: (-row["total"], str(row["plan_id"])))
    return rows[:limit]


def _demo(graph: nx.MultiDiGraph, customer_id: Any) -> None:
    print(f"loaded {graph.number_of_nodes()} nodes / {graph.number_of_edges()} edges\n")

    print(f"=== 1. Tickets for customer {customer_id} ===")
    for row in tickets_for_customer(graph, customer_id):
        print(
            f"  {row['ticket_id']:<10} {row['status']:<12} "
            f"{row['category']:<20} {row['created_at']}"
        )

    print(f"\n=== 2. Customer 360 for {customer_id} ===")
    profile = customer_360(graph, customer_id)
    if profile:
        print(
            f"  msisdn={profile['msisdn']} account_type={profile['account_type']} "
            f"status={profile['status']} kyc={profile['kyc_status']}"
        )
        print(f"  attached rows: {profile['attached_total']}")
        for name, count in profile["attached_counts"].items():
            print(f"    {name:<20}: {count}")

    print("\n=== 3. Ticket -> Escalation chains (first 8 of all) ===")
    chains = ticket_escalation_chains(graph)
    print(f"  total escalated tickets in graph: {len(chains)}")
    for row in chains[:8]:
        print(
            f"  {row['escalation_id']:<10} {str(row['level']):<4} {row['escalation_status']:<12} "
            f"<- ticket {row['ticket_id']:<10} ({row['ticket_status']}) "
            f"<- customer {row['customer_id']}"
        )

    print(f"\n=== 4. Invoice/payment reconciliation for customer {customer_id} ===")
    reconciliation = invoice_payment_reconciliation(graph, customer_id)
    if reconciliation:
        print(
            f"  invoices={reconciliation['invoices']} billed={reconciliation['total_billed']} "
            f"paid(SUCCESS)={reconciliation['total_paid_success']} "
            f"balance={reconciliation['total_balance']}"
        )
        for row in reconciliation["rows"][:6]:
            print(
                f"    {row['invoice_id']:<12} billed={row['billed']:<10} "
                f"paid={row['paid_success']:<10} balance={row['balance']:<10} "
                f"attempts={row['payment_attempts']} field={row['payment_status_field']}"
            )

    print("\n=== 5. Sites with the most alarms ===")
    for row in sites_with_most_alarms(graph, limit=8):
        print(
            f"  site {row['site_id']:<10} {row['technology']:<8} "
            f"alarms={row['alarms']:<5} {row['by_severity']}"
        )

    print("\n=== 6. Highest-degree customers ===")
    for row in top_hub_customers(graph, limit=8):
        print(
            f"  customer {row['customer_id']:<8} degree={row['degree']:<5} "
            f"{row['account_type']:<12} {row['status']}"
        )

    print("\n=== 7. Plan adoption ===")
    for row in plan_adoption(graph, limit=8):
        print(
            f"  plan {row['plan_id']:<6} {str(row['plan_name'])[:28]:<30} "
            f"subs={row['subscriptions']:<6} recharges={row['recharges']:<6} total={row['total']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the structured knowledge graph.")
    parser.add_argument("--customer", default=None, help="customer_id for the per-customer queries.")
    args = parser.parse_args()

    graph = load_graph()
    customer_id = args.customer
    if customer_id is None:
        hubs = top_hub_customers(graph, limit=1)
        customer_id = hubs[0]["customer_id"] if hubs else ""
    _demo(graph, customer_id)


if __name__ == "__main__":
    main()
