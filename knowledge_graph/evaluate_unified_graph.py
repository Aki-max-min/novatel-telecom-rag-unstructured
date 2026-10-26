"""Stats report for the unified NovaTel graph (document + structured + concept bridge).

Reads the concept layer that was built, then verifies it against the live Neo4j
database - including the connectivity proof: a shortest path from a Document to
a real Customer, which did not exist before the bridge.

Usage::

    python -m knowledge_graph.evaluate_unified_graph
    python -m knowledge_graph.evaluate_unified_graph --skip-neo4j
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional, Tuple

from knowledge_graph.concept_bridge import build_concept_layer

#: (label, concept, structured entity, code-conflict note) for the spotchecks.
SPOTCHECKS: Tuple[Tuple[str, str, str, str], ...] = (
    ("KYC", "KYC & Identity Verification", "KYCRecord", ""),
    (
        "Complaint",
        "Complaints & Grievances",
        "Ticket",
        "[structured C11 vs document C16 -> joined by CONCEPT]",
    ),
    (
        "Portability",
        "Number Portability",
        "PortingRequest",
        "[structured C18 vs document C06 -> joined by CONCEPT]",
    ),
)

#: Endpoints for the connectivity proof.
PROOF_DOCUMENT = "FAQ_C01_001"
PROOF_CUSTOMER = "Customer:1829"


def _open_session():
    from knowledge_graph.graph_loader import connection_settings
    from knowledge_graph.graph_loader import _driver as open_driver

    settings = connection_settings()
    driver = open_driver(settings)
    return driver, driver.session(database=settings["database"])


def spotcheck_counts(session, concept: str, entity_type: str) -> Dict[str, Any]:
    """How many rows and how many documents each side of a concept holds."""
    rows = session.run(
        """
        MATCH (:EntityType {entity_type: $entity})<-[:INSTANCE_OF]-(i:StructuredEntity)
        RETURN count(i) AS rows
        """,
        entity=entity_type,
    ).single()["rows"]

    documents = session.run(
        """
        MATCH (c:Concept {name: $concept})<-[:EXPRESSES_CONCEPT]-(hub)
        MATCH (d:Document)-[:BELONGS_TO_CATEGORY|MENTIONS_SERVICE]->(hub)
        WHERE d.resolved = true
        RETURN count(DISTINCT d) AS documents
        """,
        concept=concept,
    ).single()["documents"]

    realized = session.run(
        """
        MATCH (c:Concept {name: $concept})<-[:REALIZES_CONCEPT]-(t:EntityType {entity_type: $entity})
        RETURN count(t) AS c
        """,
        concept=concept,
        entity=entity_type,
    ).single()["c"]

    return {
        "rows": rows,
        "documents": documents,
        "bridged": bool(realized) and rows > 0 and documents > 0,
    }


def connectivity_proof(session) -> Dict[str, Any]:
    """Shortest path from a Document to a real Customer, and whether it needs the bridge."""
    record = session.run(
        """
        MATCH (d:Document {key: $doc}), (c:Customer {id: $cust})
        MATCH p = shortestPath((d)-[*..8]-(c))
        RETURN [n IN nodes(p) | coalesce(n.key, n.id)] AS nodes,
               [r IN relationships(p) | type(r)] AS rels,
               any(n IN nodes(p) WHERE n:Concept) AS via_concept,
               length(p) AS length
        """,
        doc=PROOF_DOCUMENT,
        cust=PROOF_CUSTOMER,
    ).single()

    if record is None:
        return {"exists": False, "path": "", "via_concept": False, "length": None}

    parts: List[str] = []
    for index, node in enumerate(record["nodes"]):
        parts.append(str(node))
        if index < len(record["rels"]):
            parts.append(f"-[{record['rels'][index]}]->")
    return {
        "exists": True,
        "path": " ".join(parts),
        "via_concept": record["via_concept"],
        "length": record["length"],
    }


def counterfactual(session) -> bool:
    """Is there still a path if the bridge relationships are excluded? Should be no."""
    record = session.run(
        """
        MATCH (d:Document {key: $doc}), (c:Customer {id: $cust})
        OPTIONAL MATCH p = shortestPath(
            (d)-[:BELONGS_TO_CATEGORY|IS_TYPE|HAS_TAG|MENTIONS_SERVICE|MENTIONS_CHANNEL
                 |MENTIONS_VERIFICATION|RELATED_TO|OF_CUSTOMER|INSTANCE_OF*..8]-(c))
        RETURN p IS NOT NULL AS exists
        """,
        doc=PROOF_DOCUMENT,
        cust=PROOF_CUSTOMER,
    ).single()
    return bool(record["exists"]) if record else False


def database_counts(session) -> Dict[str, int]:
    return {
        "concept_nodes_in_db": session.run("MATCH (n:Concept) RETURN count(n) AS c").single()["c"],
        "entity_type_nodes_in_db": session.run("MATCH (n:EntityType) RETURN count(n) AS c").single()["c"],
        "realizes_in_db": session.run(
            "MATCH (:EntityType)-[r:REALIZES_CONCEPT]->(:Concept) RETURN count(r) AS c"
        ).single()["c"],
        "expresses_in_db": session.run(
            "MATCH ()-[r:EXPRESSES_CONCEPT]->(:Concept) RETURN count(r) AS c"
        ).single()["c"],
        "instance_of_in_db": session.run(
            "MATCH (:StructuredEntity)-[r:INSTANCE_OF]->(:EntityType) RETURN count(r) AS c"
        ).single()["c"],
        "total_db_nodes": session.run("MATCH (n) RETURN count(n) AS c").single()["c"],
        "total_db_rels": session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"],
    }


def _force_utf8_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def print_block(
    stats: Dict[str, Any],
    spotchecks: Dict[str, Dict[str, Any]],
    proof: Optional[Dict[str, Any]],
    counts: Optional[Dict[str, int]],
) -> None:
    print("===== NOVATEL UNIFIED GRAPH — CROSS-LINK =====")
    print(f"concept_nodes: {stats['concept_nodes']}")
    print(f"realizes_concept_edges (EntityType->Concept): {stats['realizes_concept_edges']}")
    print(
        f"expresses_concept_edges (Category/Service->Concept): "
        f"{stats['expresses_concept_edges']}"
    )
    print(
        f"concepts_bridging_both_sides: {stats['concepts_bridging_both_sides']} / "
        f"{stats['concept_nodes']}"
    )
    print(f"unmapped_document_services: {stats['unmapped_document_services']}")
    print(f"unmapped_structured_entity_types: {stats['unmapped_structured_entity_types']}")
    print("--- BRIDGE SPOTCHECKS (concept-join must resolve the code conflicts) ---")
    for label, concept, entity, note in SPOTCHECKS:
        row = spotchecks.get(label)
        if row is None:
            print(f"{label + ':':<13}not run")
            continue
        structured = f"{entity}({row['rows']})"
        bridged = "yes" if row["bridged"] else "no"
        suffix = f"   {note}" if note else ""
        print(
            f"{label + ':':<13}structured={structured:<22} "
            f"document={row['documents']} docs   bridged={bridged}{suffix}"
        )
    print("--- CONNECTIVITY PROOF ---")
    if proof is None:
        print("shortest_path_Document_to_Customer_exists: not run")
        print("example_path: not run")
    else:
        print(
            f"shortest_path_Document_to_Customer_exists: "
            f"{'yes' if proof['exists'] else 'no'}"
        )
        print(f"example_path: {proof['path'] or '(none)'}")
    print("--- neo4j ---")
    if counts is None:
        print("concept_nodes_in_db: not run")
        print("cross_link_edges_in_db: not run")
        print("total_db_nodes: not run   total_db_rels: not run")
    else:
        cross = counts["realizes_in_db"] + counts["expresses_in_db"]
        print(f"concept_nodes_in_db: {counts['concept_nodes_in_db']}")
        print(
            f"cross_link_edges_in_db: {cross} "
            f"({counts['realizes_in_db']} REALIZES + {counts['expresses_in_db']} EXPRESSES)"
        )
        print(
            f"total_db_nodes: {counts['total_db_nodes']}   "
            f"total_db_rels: {counts['total_db_rels']}"
        )
    print("=======================================")


def print_notes(
    stats: Dict[str, Any],
    proof: Optional[Dict[str, Any]],
    without_bridge: Optional[bool],
    counts: Optional[Dict[str, int]],
) -> None:
    print()
    print("notes:")
    print(
        "  The join key is the CONCEPT NAME. No query in this layer ever compares a "
        "C-code across branches - only 8 of 28 structured entity types agree with the "
        "document branch on their code."
    )
    print(
        f"  Concept vocabulary comes from {stats['vocabulary_source']}; no parallel "
        "names are invented."
    )
    if stats["concepts_structured_side_only"]:
        print(
            f"  Structured-side-only concepts: {stats['concepts_structured_side_only']} "
            "- no document category or service covers them."
        )
    print(
        "  Unmapped document services are left unmapped on purpose: DND Activation and "
        "Refund have no concept any structured table realizes, and Loyalty Redemption "
        "was not in the seeded mapping. Mapping them would invent a bridge to nothing."
    )
    if proof and proof["exists"]:
        print(
            f"  The proof path is {proof['length']} hops and passes through a Concept: "
            f"{proof['via_concept']}."
        )
    if without_bridge is not None:
        print(
            f"  Counterfactual - same path with the bridge relationships excluded: "
            f"{'still exists' if without_bridge else 'does NOT exist'}. "
            "That absence is what the concept layer fixed."
        )
    if counts is not None:
        print(
            f"  INSTANCE_OF carries the bridge from the EntityType schema node down to "
            f"the {counts['instance_of_in_db']} real rows. Without it the path stops at "
            "the type and never reaches a Customer."
        )


def main() -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Evaluate the unified graph bridge.")
    parser.add_argument("--skip-neo4j", action="store_true", help="Report db figures as 'not run'.")
    args = parser.parse_args()

    layer = build_concept_layer()
    stats = layer["stats"]

    spotchecks: Dict[str, Dict[str, Any]] = {}
    proof: Optional[Dict[str, Any]] = None
    without_bridge: Optional[bool] = None
    counts: Optional[Dict[str, int]] = None

    if not args.skip_neo4j:
        try:
            driver, session = _open_session()
        except Exception as error:  # noqa: BLE001 - Neo4j is optional
            print(f"(neo4j unavailable: {error})", file=sys.stderr)
            driver = session = None
        if session is not None:
            try:
                for label, concept, entity, _ in SPOTCHECKS:
                    spotchecks[label] = spotcheck_counts(session, concept, entity)
                proof = connectivity_proof(session)
                without_bridge = counterfactual(session)
                counts = database_counts(session)
            finally:
                session.close()
                driver.close()

    print_block(stats, spotchecks, proof, counts)
    print_notes(stats, proof, without_bridge, counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
