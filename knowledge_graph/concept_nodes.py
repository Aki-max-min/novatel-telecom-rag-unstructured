"""Concept metadata for the document graph (E13 KG fixes, step 3): the structured side joins the graph by METADATA ONLY.

Adds, to the graph build:
  * 23 ``Concept`` nodes (the shared concept vocabulary of the ontology crosswalk), each with a ``tables`` property - the NAMES of the
    structured tables that realise the concept. No rows, no columns, no values;
  * ``EXPRESSES_CONCEPT`` edges from document Categories (22) and Services (11) to their Concept - 33 in all.

The join key is the concept NAME, never the C-code: the two branches assigned C01-C29 to different things (structured C11 = tickets,
document C16 = Complaints), so only 8 of the 28 crosswalk rows agree on a code. Concepts that share a category (Plan Catalogue/Subscription
on C02, Payments/Recharge on C03, Network Coverage/Network Outages on C08) stay separate nodes; the ``GraphIndex`` accessors return their
document groups deduplicated.

The vocabulary and mappings come from ``concept_bridge`` (crosswalk + SERVICE_CONCEPT_MAPPING) - nothing is invented here. Retrieval
(``graph_expand``, ``related_neighbours``) ignores these labels, so nothing about ranking changes.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from knowledge_graph.concept_bridge import SERVICE_CONCEPT_MAPPING, concept_id, concept_vocabulary, load_crosswalk


def build_concept_metadata(nodes: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Concept nodes and EXPRESSES_CONCEPT edges for the graph whose node list is ``nodes`` (entity + content nodes)."""
    nodes = list(nodes)
    category_keys = {n["key"] for n in nodes if n["label"] == "Category"}
    service_keys = {n["key"] for n in nodes if n["label"] == "Service"}

    crosswalk = load_crosswalk()
    rows = crosswalk["rows"]
    vocabulary = concept_vocabulary(crosswalk)
    vocabulary_set = set(vocabulary)

    concept_nodes: List[Dict[str, Any]] = []
    for name in vocabulary:
        tables = sorted(r["structured_table"] for r in rows if r["shared_domain_concept"] == name)
        categories = sorted({r["document_category_code"] for r in rows
                             if r["shared_domain_concept"] == name and r["document_category_code"] in category_keys})
        services = sorted(s for s, c in SERVICE_CONCEPT_MAPPING.items() if c == name and s in service_keys)
        concept_nodes.append({
            "id": concept_id(name),
            "label": "Concept",
            "key": name,
            "properties": {
                "name": name,
                "vocabulary_source": "structured_document_crosswalk.shared_domain_concept",
                "tables": tables,                                   # table NAMES only (metadata, no rows)
                "document_categories": ", ".join(categories),
                "document_services": ", ".join(services),
                "bridges_both_sides": bool(tables) and bool(categories or services),
            },
        })

    edges: List[Dict[str, Any]] = []
    seen = set()
    for row in sorted(rows, key=lambda r: (r["document_category_code"], r["shared_domain_concept"])):
        code, name = row["document_category_code"], row["shared_domain_concept"]
        if not code or name not in vocabulary_set or code not in category_keys or (code, name) in seen:
            continue
        seen.add((code, name))
        edges.append({
            "source": f"Category::{code}", "target": concept_id(name), "type": "EXPRESSES_CONCEPT",
            "source_field": "structured_document_crosswalk",
            "properties": {"via": "Category", "document_category_code": code,
                           "mapping_source": "structured_document_crosswalk",
                           "code_agrees_with_structured": bool(row["codes_agree"])},
        })
    for service in sorted(service_keys):
        name = SERVICE_CONCEPT_MAPPING.get(service)
        if name is None or name not in vocabulary_set:
            continue
        edges.append({
            "source": f"Service::{service}", "target": concept_id(name), "type": "EXPRESSES_CONCEPT",
            "source_field": "service_concept_mapping",
            "properties": {"via": "Service", "document_service": service, "mapping_source": "service_concept_mapping"},
        })

    stats = {"concept_nodes": len(concept_nodes), "expresses_concept_edges": len(edges),
             "via_category": sum(e["properties"]["via"] == "Category" for e in edges),
             "via_service": sum(e["properties"]["via"] == "Service" for e in edges),
             "tables_mapped": sum(len(n["properties"]["tables"]) for n in concept_nodes)}
    return {"nodes": concept_nodes, "edges": edges, "stats": stats}
