"""The shared CONCEPT layer that bridges the document KG and the structured KG.

The two graphs describe the same telecom business from opposite ends: 148
documents on one side, 43,928 database rows on the other. They are joined here -
and **only** here - through a shared concept vocabulary.

**The join key is the concept name, never the C-code.** The two branches
independently assigned C01-C29 codes to different things: structured `C11` is
tickets while document `C16` is Complaints; structured `C18` is porting while
document `C06` is Number Portability; structured `C05` is payments while
document `C05` is SIM cards. Joining on code would succeed and be silently
wrong. Every bridge edge in this module is built from an explicit mapping table.

Three edge types are written:

* ``(EntityType)-[:REALIZES_CONCEPT]->(Concept)`` - the structured side. A table
  realizes a concept.
* ``(Category|Service)-[:EXPRESSES_CONCEPT]->(Concept)`` - the document side. A
  document category or an extracted service expresses a concept.
* ``(instance)-[:INSTANCE_OF]->(EntityType)`` - optional but on by default.
  Without it the bridge only reaches the schema node ``EntityType:Customer``,
  not the 1,809 real customers, and a Document->Customer path does not exist.

Vocabulary source: the ``structured_document_crosswalk`` written in Phase 4.
This module never invents a concept name.

Usage::

    python -m knowledge_graph.concept_bridge                 # build + report
    python -m knowledge_graph.concept_bridge --load          # + MERGE into Neo4j
    python -m knowledge_graph.concept_bridge --load --no-instance-of
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from knowledge_graph.entity_extractor import OUTPUT_DIR
from knowledge_graph.graph_builder import GRAPH_JSON_PATH
from knowledge_graph.structured_graph_builder import SCHEMA_JSON_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY_SCHEMA = REPO_ROOT / "ontology" / "ontology_schema.json"
CONCEPT_LAYER_PATH = OUTPUT_DIR / "concept_layer.json"

CONCEPT_PREFIX = "Concept::"
ENTITY_TYPE_PREFIX = "EntityType:"

#: Document Service -> canonical concept.
#:
#: The right-hand side must be a value that already exists in the crosswalk's
#: shared_domain_concept column; anything else is rejected at build time rather
#: than quietly creating a parallel vocabulary ("KYC" alongside
#: "KYC & Identity Verification").
#:
#: Two seeded targets have no concept in the vocabulary, because the structured
#: schema has no table for them, and are therefore deliberately absent:
#:   * DND Activation  -> "DND"    : no DND table exists.
#:   * Refund          -> "Refund" : refunds live inside payment_transactions,
#:                                   which realizes Payments, not a Refund concept.
#: Mapping either one would invent a concept that nothing on the structured side
#: realizes, producing a bridge that bridges nothing.
SERVICE_CONCEPT_MAPPING: Dict[str, str] = {
    "KYC Verification": "KYC & Identity Verification",
    "Number Portability": "Number Portability",
    "Recharge": "Recharge",
    "Bill Payment": "Payments",
    "Complaint Registration": "Complaints & Grievances",
    "Roaming Activation": "Roaming",
    "SIM Swap": "SIM Card Services",
    "eSIM Activation": "SIM Card Services",
    # "Plan Change" could argue for either Plan Catalogue or Subscription. It is
    # mapped to Plan Catalogue because changing plan is an act against the plan
    # catalogue; the Subscription concept is realized by the subscriptions table.
    "Plan Change": "Plan Catalogue",
    "Broadband/FTTH Installation": "Broadband & FTTH Services",
    "Mobile Number Update": "Customer Account",
    # Seeded as "VAS Subscription" -> VAS. Kept because the concept exists, but
    # the document branch has no Service by this name, so it produces no edge.
    "VAS Subscription": "Value Added Services",
}


def load_crosswalk(path: Path = ONTOLOGY_SCHEMA) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    if "structured_document_crosswalk" not in schema:
        raise KeyError(
            "structured_document_crosswalk missing from ontology_schema.json - "
            "run the Phase 4 ontology extension first."
        )
    return schema["structured_document_crosswalk"]


def concept_vocabulary(crosswalk: Dict[str, Any]) -> List[str]:
    """The canonical concept names - distinct shared_domain_concept values."""
    return sorted({row["shared_domain_concept"] for row in crosswalk["rows"] if row["shared_domain_concept"]})


def concept_id(name: str) -> str:
    return f"{CONCEPT_PREFIX}{name}"


def _load_document_graph(path: Path = GRAPH_JSON_PATH) -> Dict[str, List[str]]:
    """Keys of the document branch's Category and Service nodes."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the document KG first: "
            f"python -m knowledge_graph.graph_builder"
        )
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    keys: Dict[str, List[str]] = {"Category": [], "Service": []}
    for node in payload["nodes"]:
        if node["label"] in keys:
            keys[node["label"]].append(node["key"])
    return {label: sorted(values) for label, values in keys.items()}


def _load_entity_type_nodes(path: Path = SCHEMA_JSON_PATH) -> List[Dict[str, Any]]:
    """The 28 EntityType nodes from the structured schema view."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the structured KG first: "
            f"python -m knowledge_graph.structured_graph_builder"
        )
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return [node for node in payload["nodes"] if node["label"] == "EntityType"]


def build_concept_layer() -> Dict[str, Any]:
    """Build concept nodes and the bridge edges. Pure data, no database."""
    crosswalk = load_crosswalk()
    rows = crosswalk["rows"]
    vocabulary = concept_vocabulary(crosswalk)
    vocabulary_set = set(vocabulary)

    document_keys = _load_document_graph()
    entity_type_nodes = _load_entity_type_nodes()

    # --- concept nodes ----------------------------------------------------
    concepts: List[Dict[str, Any]] = []
    for name in vocabulary:
        entities = sorted(
            row["structured_entity_type"]
            for row in rows
            if row["shared_domain_concept"] == name
        )
        categories = sorted(
            {
                row["document_category_code"]
                for row in rows
                if row["shared_domain_concept"] == name and row["document_category_code"]
            }
        )
        services = sorted(
            service
            for service, concept in SERVICE_CONCEPT_MAPPING.items()
            if concept == name and service in document_keys["Service"]
        )
        concepts.append(
            {
                "id": concept_id(name),
                "label": "Concept",
                "key": name,
                "properties": {
                    "label": "Concept",
                    "name": name,
                    "vocabulary_source": "structured_document_crosswalk.shared_domain_concept",
                    "structured_entity_types": ", ".join(entities),
                    "document_categories": ", ".join(categories),
                    "document_services": ", ".join(services),
                    "bridges_both_sides": bool(entities) and bool(categories or services),
                },
            }
        )

    # --- structured side: EntityType -> Concept ---------------------------
    realizes: List[Dict[str, Any]] = []
    unmapped_entity_types: List[str] = []
    for row in sorted(rows, key=lambda r: r["structured_entity_type"]):
        entity = row["structured_entity_type"]
        name = row["shared_domain_concept"]
        if name not in vocabulary_set:
            unmapped_entity_types.append(entity)
            continue
        realizes.append(
            {
                "source": f"{ENTITY_TYPE_PREFIX}{entity}",
                "target": concept_id(name),
                "type": "REALIZES_CONCEPT",
                "properties": {
                    "branch": "structured",
                    "source_table": row["structured_table"],
                    "structured_category_code": row["structured_category_code"],
                    "mapping_source": "structured_document_crosswalk",
                },
            }
        )

    # --- document side: Category -> Concept, Service -> Concept -----------
    expresses: List[Dict[str, Any]] = []
    seen_category_pairs = set()
    for row in sorted(rows, key=lambda r: (r["document_category_code"], r["shared_domain_concept"])):
        code = row["document_category_code"]
        name = row["shared_domain_concept"]
        if not code or name not in vocabulary_set:
            continue
        if code not in document_keys["Category"]:
            continue
        pair = (code, name)
        if pair in seen_category_pairs:
            continue
        seen_category_pairs.add(pair)
        expresses.append(
            {
                "source": f"Category::{code}",
                "target": concept_id(name),
                "type": "EXPRESSES_CONCEPT",
                "properties": {
                    "branch": "document",
                    "via": "Category",
                    "document_category_code": code,
                    "document_category_name": row["document_category_name"],
                    "mapping_source": "structured_document_crosswalk",
                    "code_agrees_with_structured": row["codes_agree"],
                },
            }
        )

    unmapped_services: List[str] = []
    mapping_without_service: List[str] = []
    for service in document_keys["Service"]:
        name = SERVICE_CONCEPT_MAPPING.get(service)
        if name is None:
            unmapped_services.append(service)
            continue
        if name not in vocabulary_set:
            unmapped_services.append(service)
            continue
        expresses.append(
            {
                "source": f"Service::{service}",
                "target": concept_id(name),
                "type": "EXPRESSES_CONCEPT",
                "properties": {
                    "branch": "document",
                    "via": "Service",
                    "document_service": service,
                    "mapping_source": "service_concept_mapping",
                },
            }
        )
    for service, name in sorted(SERVICE_CONCEPT_MAPPING.items()):
        if service not in document_keys["Service"]:
            mapping_without_service.append(f"{service} -> {name}")

    # --- stats ------------------------------------------------------------
    bridged = [c["key"] for c in concepts if c["properties"]["bridges_both_sides"]]
    structured_only = [c["key"] for c in concepts if not c["properties"]["bridges_both_sides"]]

    stats = {
        "concept_nodes": len(concepts),
        "vocabulary_source": "structured_document_crosswalk.shared_domain_concept",
        "realizes_concept_edges": len(realizes),
        "expresses_concept_edges": len(expresses),
        "expresses_via_category": sum(1 for e in expresses if e["properties"]["via"] == "Category"),
        "expresses_via_service": sum(1 for e in expresses if e["properties"]["via"] == "Service"),
        "concepts_bridging_both_sides": len(bridged),
        "concepts_structured_side_only": structured_only,
        "unmapped_document_services": sorted(unmapped_services),
        "unmapped_structured_entity_types": sorted(unmapped_entity_types),
        "mapping_entries_without_a_document_service": sorted(mapping_without_service),
        "entity_type_nodes": len(entity_type_nodes),
    }

    return {
        "concepts": concepts,
        "entity_type_nodes": entity_type_nodes,
        "realizes_edges": realizes,
        "expresses_edges": expresses,
        "service_concept_mapping": dict(sorted(SERVICE_CONCEPT_MAPPING.items())),
        "stats": stats,
    }


def save_concept_layer(layer: Dict[str, Any], path: Path = CONCEPT_LAYER_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(layer, handle, indent=2, ensure_ascii=False)
    return path


# ---------------------------------------------------------------------------
# Neo4j
# ---------------------------------------------------------------------------
BATCH_SIZE = 1000


def load_into_neo4j(layer: Dict[str, Any], instance_of: bool = True) -> Dict[str, Any]:
    """MERGE the concept layer into Neo4j. Idempotent."""
    from knowledge_graph.graph_loader import connection_settings
    from knowledge_graph.graph_loader import _driver as open_driver

    settings = connection_settings()
    driver = open_driver(settings)
    written: Dict[str, int] = {}
    try:
        with driver.session(database=settings["database"]) as session:
            for label in ("Concept", "EntityType"):
                session.run(
                    f"CREATE CONSTRAINT novatel_{label.lower()}_id IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                )

            session.run(
                "UNWIND $rows AS row MERGE (n:Concept {id: row.id}) SET n += row.props",
                rows=[{"id": c["id"], "props": c["properties"]} for c in layer["concepts"]],
            )
            written["Concept"] = len(layer["concepts"])

            session.run(
                "UNWIND $rows AS row MERGE (n:EntityType {id: row.id}) SET n += row.props",
                rows=[
                    {"id": n["id"], "props": n["properties"]}
                    for n in layer["entity_type_nodes"]
                ],
            )
            written["EntityType"] = len(layer["entity_type_nodes"])

            session.run(
                "UNWIND $rows AS row "
                "MATCH (a:EntityType {id: row.source}) MATCH (b:Concept {id: row.target}) "
                "MERGE (a)-[r:REALIZES_CONCEPT]->(b) SET r += row.props",
                rows=[
                    {"source": e["source"], "target": e["target"], "props": e["properties"]}
                    for e in layer["realizes_edges"]
                ],
            )
            written["REALIZES_CONCEPT"] = len(layer["realizes_edges"])

            session.run(
                "UNWIND $rows AS row "
                "MATCH (a {id: row.source}) MATCH (b:Concept {id: row.target}) "
                "MERGE (a)-[r:EXPRESSES_CONCEPT]->(b) SET r += row.props",
                rows=[
                    {"source": e["source"], "target": e["target"], "props": e["properties"]}
                    for e in layer["expresses_edges"]
                ],
            )
            written["EXPRESSES_CONCEPT"] = len(layer["expresses_edges"])

            if instance_of:
                # Without this the bridge stops at the EntityType schema node and
                # no Document -> Customer path exists. One edge per row: 43,928.
                total = 0
                for node in layer["entity_type_nodes"]:
                    entity = node["properties"]["entity_type"]
                    record = session.run(
                        f"MATCH (i:{entity}:StructuredEntity) "
                        f"WITH i MATCH (t:EntityType {{id: $type_id}}) "
                        f"MERGE (i)-[:INSTANCE_OF]->(t) "
                        f"RETURN count(*) AS c",
                        type_id=node["id"],
                    ).single()
                    total += record["c"] if record else 0
                written["INSTANCE_OF"] = total

            counts = {
                "concept_nodes_in_db": session.run(
                    "MATCH (n:Concept) RETURN count(n) AS c"
                ).single()["c"],
                "entity_type_nodes_in_db": session.run(
                    "MATCH (n:EntityType) RETURN count(n) AS c"
                ).single()["c"],
                "realizes_in_db": session.run(
                    "MATCH (:EntityType)-[r:REALIZES_CONCEPT]->(:Concept) RETURN count(r) AS c"
                ).single()["c"],
                "expresses_in_db": session.run(
                    "MATCH ()-[r:EXPRESSES_CONCEPT]->(:Concept) RETURN count(r) AS c"
                ).single()["c"],
                "instance_of_in_db": session.run(
                    "MATCH (:StructuredEntity)-[r:INSTANCE_OF]->(:EntityType) RETURN count(r) AS c"
                ).single()["c"],
            }
    finally:
        driver.close()
    return {"written": written, "counts": counts}


def _force_utf8_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main() -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Build the shared concept layer.")
    parser.add_argument("--load", action="store_true", help="MERGE the layer into Neo4j.")
    parser.add_argument(
        "--no-instance-of",
        action="store_true",
        help="Skip the 43,928 INSTANCE_OF edges (bridge then stops at the schema node).",
    )
    args = parser.parse_args()

    layer = build_concept_layer()
    path = save_concept_layer(layer)
    stats = layer["stats"]

    print("===== CONCEPT LAYER =====")
    print(f"concept vocabulary        : {stats['concept_nodes']} concepts")
    print(f"  source                  : {stats['vocabulary_source']}")
    print(f"REALIZES_CONCEPT edges    : {stats['realizes_concept_edges']} (EntityType -> Concept)")
    print(
        f"EXPRESSES_CONCEPT edges   : {stats['expresses_concept_edges']} "
        f"(Category {stats['expresses_via_category']} + Service {stats['expresses_via_service']})"
    )
    print(
        f"concepts bridging both    : {stats['concepts_bridging_both_sides']} / "
        f"{stats['concept_nodes']}"
    )
    if stats["concepts_structured_side_only"]:
        print(f"  structured side only    : {stats['concepts_structured_side_only']}")
    print(f"unmapped document services: {stats['unmapped_document_services']}")
    print(f"unmapped entity types     : {stats['unmapped_structured_entity_types']}")
    if stats["mapping_entries_without_a_document_service"]:
        print(
            f"mapping entries with no matching Service node: "
            f"{stats['mapping_entries_without_a_document_service']}"
        )
    print(f"written                   : {path}")

    if args.load:
        print()
        print("loading into Neo4j...")
        result = load_into_neo4j(layer, instance_of=not args.no_instance_of)
        for name, count in result["written"].items():
            print(f"  merged {count:>6} {name}")
        print("verification:")
        for name, count in result["counts"].items():
            print(f"  {name:<26}: {count}")
    print("=" * 25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
