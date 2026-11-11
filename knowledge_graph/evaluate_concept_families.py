"""Per-family acceptance check for the concept-name mention rule (docs/E13_kg_fixes2.md, step 2). Read-only measurement.

For each shared concept name, in alphabetical order, with the families kept so far:
  (a) newly covered documents (no content concept before, one now);
  (b) documents mentioning the concept in the body (must be <= 10% of 148, i.e. <= 14) and growth = mentioning documents that are not
      already in the concept's category/service group (must be <= 2);
  (c) evidence check: the evidence phrase is present in the document body for every new edge (must be 100%).
A family is KEPT only if (b) and (c) hold and it newly covers at least one document.

    python -m knowledge_graph.evaluate_concept_families            # table only
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Iterable, List, Sequence

from knowledge_graph import content_extractor as ce
from knowledge_graph.concept_bridge import SERVICE_CONCEPT_MAPPING, concept_vocabulary, load_crosswalk
from knowledge_graph.concept_nodes import build_concept_metadata
from knowledge_graph.entity_extractor import extract_entities, load_documents

MAX_SHARE = 0.10
MAX_GROWTH = 2


def concept_groups(documents: List[Dict[str, Any]], per_document: Dict[str, Dict[str, List[str]]], nodes) -> Dict[str, set]:
    """concept -> documents already associated with it through its categories and its mapped services."""
    meta = build_concept_metadata(nodes)
    category_of = {d["document_id"]: d.get("category") for d in documents}
    groups: Dict[str, set] = {}
    for node in meta["nodes"]:
        props = node["properties"]
        cats = {c for c in props["document_categories"].split(", ") if c}
        services = {s for s in props["document_services"].split(", ") if s}
        docs = {i for i, c in category_of.items() if c in cats}
        docs |= {i for i, v in per_document.items() if services & set(v.get("Service", []))}
        groups[node["key"]] = docs
    return groups


def measure(documents: List[Dict[str, Any]], kept: Sequence[str], candidate: str, baseline: Dict[str, Any]) -> Dict[str, Any]:
    n = len(documents)
    before = ce.extract_content(documents, families=tuple(kept))
    after = ce.extract_content(documents, families=tuple(kept) + (candidate,))
    new_edges = [e for e in after["concept_mention_edges"] if e["target"] == f"Concept::{candidate}"]
    docs_mentioning = {e["source"].split("::", 1)[1] for e in new_edges}
    by_id = {d["document_id"]: d for d in documents}
    passed = sum(1 for e in new_edges
                 if ce._compile(e["properties"]["evidence_span"]).search(ce.body_text(by_id[e["source"].split("::", 1)[1]])))
    group = baseline["groups"].get(candidate, set())
    growth = len(docs_mentioning - group)
    newly = after["stats"]["documents_with_any_content_concept"] - before["stats"]["documents_with_any_content_concept"]
    ok_b = len(docs_mentioning) <= int(MAX_SHARE * n) and growth <= MAX_GROWTH
    ok_c = passed == len(new_edges)
    return {"concept": candidate, "docs_mentioning": len(docs_mentioning), "group_size": len(group), "growth": growth,
            "newly_covered": newly, "covered_after": after["stats"]["documents_with_any_content_concept"],
            "evidence_passed": f"{passed}/{len(new_edges)}", "b_ok": ok_b, "c_ok": ok_c,
            "keep": bool(ok_b and ok_c and newly >= 1), "docs": sorted(docs_mentioning)}


def run(documents=None, kept: Iterable[str] = ()) -> List[Dict[str, Any]]:
    documents = list(documents) if documents is not None else load_documents()
    base = ce.extract_content(documents, families=())
    entities = extract_entities(documents)
    baseline = {"groups": concept_groups(documents, base["per_document"], entities["nodes"] + base["nodes"])}
    kept = list(kept)
    rows = []
    for name in sorted(concept_vocabulary(load_crosswalk())):
        row = measure(documents, kept, name, baseline)
        rows.append(row)
        if row["keep"]:
            kept.append(name)
    return rows


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = run()
    print(f"{'concept':<34}{'docs':>5}{'group':>6}{'growth':>7}{'new':>5}{'cover':>6}  evidence  b  c  keep")
    for r in rows:
        print(f"{r['concept']:<34}{r['docs_mentioning']:>5}{r['group_size']:>6}{r['growth']:>7}{r['newly_covered']:>5}"
              f"{r['covered_after']:>6}  {r['evidence_passed']:<8} {str(r['b_ok'])[0]}  {str(r['c_ok'])[0]}  {'KEEP' if r['keep'] else 'drop'}")
    kept = [r["concept"] for r in rows if r["keep"]]
    print("kept:", kept)


if __name__ == "__main__":
    main()
