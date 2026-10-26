"""Cross-branch queries over the unified NovaTel graph.

These are the questions neither branch can answer alone: they start in the
documentation and end in the database, or the reverse, crossing at a Concept.

Every traversal joins on the **concept name**. None of these functions ever
compares a C-code across branches - the codes conflict (structured C11=tickets
vs document C16=Complaints), so a code join would return plausible rubbish.

Runs against Neo4j (both graphs plus the concept layer must be loaded).

Usage::

    python -m knowledge_graph.unified_queries
    python -m knowledge_graph.unified_queries --concept "KYC & Identity Verification"
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

DEFAULT_SAMPLE = 5

#: Concepts used by the demo, chosen because each is a code-conflict case.
DEMO_CONCEPTS = (
    "KYC & Identity Verification",
    "Complaints & Grievances",
    "Number Portability",
)


def _session():
    from knowledge_graph.graph_loader import connection_settings
    from knowledge_graph.graph_loader import _driver as open_driver

    settings = connection_settings()
    driver = open_driver(settings)
    return driver, driver.session(database=settings["database"])


# ---------------------------------------------------------------------------
# 1. Concept -> governing documents + structured entities (+ their customers)
# ---------------------------------------------------------------------------
def unified_concept_query(
    concept_name: str, sample: int = DEFAULT_SAMPLE, session=None
) -> Dict[str, Any]:
    """Everything both branches know about one concept.

    Returns ``{documents, structured_entity_types, sample_instances}``. Sample
    instances are reached by label, using the ``entity_type`` property recorded
    on every structured node, so no per-type query has to be hardcoded.
    """
    owned = session is None
    driver = None
    if owned:
        driver, session = _session()
    try:
        documents = [
            dict(record)
            for record in session.run(
                """
                MATCH (c:Concept {name: $name})<-[:EXPRESSES_CONCEPT]-(hub)
                MATCH (d:Document)-[:BELONGS_TO_CATEGORY|MENTIONS_SERVICE]->(hub)
                WHERE d.resolved = true
                // One row per document: a document reaching the concept through
                // both its Category and a Service must not be counted twice.
                RETURN d.key AS document_id,
                       d.title AS title,
                       d.document_type AS document_type,
                       collect(DISTINCT labels(hub)[0] + ':' + hub.key) AS via
                ORDER BY document_id
                """,
                name=concept_name,
            )
        ]

        entity_types = [
            dict(record)
            for record in session.run(
                """
                MATCH (c:Concept {name: $name})<-[:REALIZES_CONCEPT]-(t:EntityType)
                OPTIONAL MATCH (i:StructuredEntity)-[:INSTANCE_OF]->(t)
                RETURN t.entity_type AS entity_type,
                       t.source_table AS source_table,
                       t.category_tag AS structured_code,
                       count(i) AS instances
                ORDER BY entity_type
                """,
                name=concept_name,
            )
        ]

        instances = [
            dict(record)
            for record in session.run(
                """
                MATCH (c:Concept {name: $name})<-[:REALIZES_CONCEPT]-(t:EntityType)
                MATCH (i:StructuredEntity)-[:INSTANCE_OF]->(t)
                OPTIONAL MATCH (i)-[:OF_CUSTOMER]->(cust:Customer)
                RETURN i.id AS instance_id,
                       i.entity_type AS entity_type,
                       coalesce(i.status, '') AS status,
                       coalesce(cust.customer_id, '') AS customer_id,
                       coalesce(cust.name, '') AS customer_name
                ORDER BY entity_type, instance_id
                LIMIT $sample
                """,
                name=concept_name,
                sample=sample,
            )
        ]
    finally:
        if owned and driver is not None:
            session.close()
            driver.close()

    return {
        "concept": concept_name,
        "documents": documents,
        "structured_entity_types": entity_types,
        "sample_instances": instances,
    }


# ---------------------------------------------------------------------------
# 2. "Everything about KYC"
# ---------------------------------------------------------------------------
def kyc_view(sample: int = DEFAULT_SAMPLE, session=None) -> Dict[str, Any]:
    """KYC policy/FAQ documents plus real KYCRecords and the customers they belong to.

    The document side is C17 + the KYC Verification service; the structured side
    is kyc_records. They meet at the concept, not at a code (here the codes
    happen to agree, which is exactly why it is a poor join key in general - it
    agrees 8 times out of 28).
    """
    owned = session is None
    driver = None
    if owned:
        driver, session = _session()
    try:
        records = [
            dict(record)
            for record in session.run(
                """
                MATCH (c:Concept {name: 'KYC & Identity Verification'})
                      <-[:REALIZES_CONCEPT]-(:EntityType {entity_type: 'KYCRecord'})
                MATCH (k:KYCRecord)-[:OF_CUSTOMER]->(cust:Customer)
                RETURN k.kyc_id AS kyc_id,
                       k.kyc_type AS kyc_type,
                       k.status AS kyc_status,
                       cust.customer_id AS customer_id,
                       cust.name AS customer_name,
                       cust.kyc_status AS customer_kyc_status
                ORDER BY kyc_id
                LIMIT $sample
                """,
                sample=sample,
            )
        ]
        mismatches = session.run(
            """
            MATCH (k:KYCRecord)-[:OF_CUSTOMER]->(cust:Customer)
            WHERE k.status <> cust.kyc_status
            RETURN count(*) AS mismatched
            """
        ).single()["mismatched"]
    finally:
        if owned and driver is not None:
            session.close()
            driver.close()

    view = unified_concept_query("KYC & Identity Verification", sample=sample)
    view["kyc_records"] = records
    view["record_vs_customer_status_mismatches"] = mismatches
    return view


# ---------------------------------------------------------------------------
# 3. Complaint view: documents + real Ticket -> Escalation chains
# ---------------------------------------------------------------------------
def complaint_view(sample: int = DEFAULT_SAMPLE, session=None) -> Dict[str, Any]:
    """Complaint documentation beside the actual escalated tickets.

    This is the code-conflict case: the structured side files tickets under
    C11, the document side files complaints under C16. Only the concept
    ``Complaints & Grievances`` joins them.
    """
    owned = session is None
    driver = None
    if owned:
        driver, session = _session()
    try:
        chains = [
            dict(record)
            for record in session.run(
                """
                MATCH (c:Concept {name: 'Complaints & Grievances'})
                      <-[:REALIZES_CONCEPT]-(:EntityType {entity_type: 'EscalationCase'})
                MATCH (e:EscalationCase)-[:ESCALATES_TICKET]->(t:Ticket)-[:OF_CUSTOMER]->(cust:Customer)
                RETURN e.escalation_id AS escalation_id,
                       e.level AS level,
                       e.status AS escalation_status,
                       t.ticket_id AS ticket_id,
                       t.category AS ticket_category,
                       t.status AS ticket_status,
                       cust.customer_id AS customer_id
                ORDER BY escalation_id
                LIMIT $sample
                """,
                sample=sample,
            )
        ]
        totals = dict(
            session.run(
                """
                MATCH (t:Ticket) WITH count(t) AS tickets
                MATCH (e:EscalationCase) WITH tickets, count(e) AS escalations
                MATCH (:EscalationCase)-[r:ESCALATES_TICKET]->(:Ticket)
                RETURN tickets, escalations, count(r) AS escalated_tickets
                """
            ).single()
        )
        codes = dict(
            session.run(
                """
                MATCH (:EntityType {entity_type: 'Ticket'})-[:REALIZES_CONCEPT]->(c:Concept)
                MATCH (cat:Category)-[:EXPRESSES_CONCEPT]->(c)
                RETURN c.name AS concept,
                       head(collect(DISTINCT cat.key)) AS document_code
                """
            ).single()
        )
    finally:
        if owned and driver is not None:
            session.close()
            driver.close()

    view = unified_concept_query("Complaints & Grievances", sample=sample)
    view["escalation_chains"] = chains
    view["totals"] = totals
    view["code_conflict"] = {
        "structured_code": "C11 (tickets)",
        "document_code": codes.get("document_code", ""),
        "joined_on": codes.get("concept", ""),
    }
    return view


# ---------------------------------------------------------------------------
# 4. Coverage of the bridge
# ---------------------------------------------------------------------------
def bridge_coverage(session=None) -> List[Dict[str, Any]]:
    """Per concept: how many documents and how many rows sit on each side."""
    owned = session is None
    driver = None
    if owned:
        driver, session = _session()
    try:
        rows = [
            dict(record)
            for record in session.run(
                """
                MATCH (c:Concept)
                OPTIONAL MATCH (c)<-[:REALIZES_CONCEPT]-(t:EntityType)
                OPTIONAL MATCH (i:StructuredEntity)-[:INSTANCE_OF]->(t)
                WITH c, count(DISTINCT t) AS entity_types, count(i) AS rows
                OPTIONAL MATCH (c)<-[:EXPRESSES_CONCEPT]-(hub)
                OPTIONAL MATCH (d:Document)-[:BELONGS_TO_CATEGORY|MENTIONS_SERVICE]->(hub)
                WHERE d.resolved = true
                RETURN c.name AS concept,
                       entity_types,
                       rows,
                       count(DISTINCT hub) AS document_hubs,
                       count(DISTINCT d) AS documents
                ORDER BY documents DESC, rows DESC, concept
                """
            )
        ]
    finally:
        if owned and driver is not None:
            session.close()
            driver.close()
    return rows


def _force_utf8_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _print_concept(view: Dict[str, Any]) -> None:
    print(f"=== concept: {view['concept']} ===")
    print(f"  documents ({len(view['documents'])}):")
    for row in view["documents"][:8]:
        print(
            f"    {row['document_id']:<26} {row['document_type']:<16} "
            f"via {', '.join(row['via'])}"
        )
    if len(view["documents"]) > 8:
        print(f"    ... and {len(view['documents']) - 8} more")
    print("  structured entity types:")
    for row in view["structured_entity_types"]:
        print(
            f"    {row['entity_type']:<20} table={row['source_table']:<22} "
            f"code={row['structured_code']:<5} rows={row['instances']}"
        )
    print("  sample instances:")
    for row in view["sample_instances"]:
        customer = f" customer={row['customer_id']} {row['customer_name']}" if row["customer_id"] else ""
        print(f"    {row['instance_id']:<24} status={row['status']:<12}{customer}")


def main() -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Cross-branch queries over the unified graph.")
    parser.add_argument("--concept", default=None, help="Run query 1 for one concept only.")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    args = parser.parse_args()

    driver, session = _session()
    try:
        if args.concept:
            _print_concept(unified_concept_query(args.concept, args.sample, session=session))
            return 0

        print("### 1. unified_concept_query for the three code-conflict concepts\n")
        for name in DEMO_CONCEPTS:
            _print_concept(unified_concept_query(name, args.sample, session=session))
            print()

        print("### 2. Everything about KYC\n")
        kyc = kyc_view(args.sample, session=session)
        print(f"  documents={len(kyc['documents'])}  kyc_records sampled={len(kyc['kyc_records'])}")
        for row in kyc["kyc_records"]:
            print(
                f"    kyc {row['kyc_id']:<8} {row['kyc_type']:<12} {row['kyc_status']:<12} "
                f"-> customer {row['customer_id']} ({row['customer_name']}) "
                f"customer_kyc={row['customer_kyc_status']}"
            )
        print(
            f"  KYCRecord.status disagreeing with Customer.kyc_status: "
            f"{kyc['record_vs_customer_status_mismatches']}"
        )
        print()

        print("### 3. Complaint view: documents + real escalation chains\n")
        complaints = complaint_view(args.sample, session=session)
        print(f"  code conflict: {complaints['code_conflict']}")
        print(f"  totals: {complaints['totals']}")
        for row in complaints["escalation_chains"]:
            print(
                f"    escalation {row['escalation_id']:<8} {row['level']:<4} "
                f"{row['escalation_status']:<10} <- ticket {row['ticket_id']:<8} "
                f"({row['ticket_category']}/{row['ticket_status']}) <- customer {row['customer_id']}"
            )
        print()

        print("### 4. Bridge coverage per concept\n")
        print(f"  {'concept':<32} {'docs':>5} {'hubs':>5} {'types':>6} {'rows':>7}")
        for row in bridge_coverage(session=session):
            print(
                f"  {row['concept']:<32} {row['documents']:>5} {row['document_hubs']:>5} "
                f"{row['entity_types']:>6} {row['rows']:>7}"
            )
    finally:
        session.close()
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
