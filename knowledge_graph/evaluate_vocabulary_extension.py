"""Acceptance check of the vocabulary overlay (docs/E13_kg_fixes3.md). Measures per concept over ALL documents and applies the pre-declared rule:

  phrase hub rule : a single phrase that matches more than 10% of the documents (14 of 148) is dropped first, from corpus counts only;
  (a) a concept matches at most 14 documents and an EXISTING concept grows by at most 2 documents over its existing group;
  (b) a NEW concept links at least 2 documents;
  (c) 100% of the new edges have their evidence phrase in the body (a proxy, not validation).
Decisions are recorded in the overlay (``dropped``, ``dropped_phrases``); no rule is deleted. The order of the concepts does not change a decision.

    python -m knowledge_graph.evaluate_vocabulary_extension            # table + decisions (read-only)
    python -m knowledge_graph.evaluate_vocabulary_extension --apply    # also write the decisions into knowledge_graph/vocabulary_extension.json
"""

from __future__ import annotations

import copy
import csv
import json
import sys
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from knowledge_graph import content_extractor as ce
from knowledge_graph import vocabulary_overlay as vo

MAX_SHARE = 0.10
MAX_GROWTH = 2
MIN_NEW_DOCUMENTS = 2


def _phrase_documents(documents, concept: str, phrase: str, excluded) -> Set[str]:
    pattern = ce._compile(phrase)
    return {d["document_id"] for d in documents
            if (d["document_id"], concept) not in excluded and pattern.search(ce.body_text(d))}


def _evidence_in_body(documents, document_id: str, record: Dict[str, Any]) -> bool:
    document = next(d for d in documents if d["document_id"] == document_id)
    return bool(ce._compile(record["evidence_span"]).search(ce.body_text(document)))


def evaluate(documents: Iterable[Dict[str, Any]], raw: Dict[str, Any], groups: Dict[str, Set[str]], baseline_covered: Set[str],
             five_label_covered: Optional[Set[str]] = None, families: Optional[Tuple[str, ...]] = None) -> Dict[str, Any]:
    """``baseline_covered`` = documents with a content concept before the task (the 'newly covered' reference);
    ``five_label_covered`` = documents covered by the five original labels alone (the base of ``coverage_after``)."""
    documents = list(documents)
    n = len(documents)
    max_docs = int(MAX_SHARE * n)
    five_label_covered = set(baseline_covered if five_label_covered is None else five_label_covered)
    cleared = copy.deepcopy(raw)
    cleared["dropped"], cleared["dropped_phrases"] = {}, {}
    excluded = {(e["document_id"], e["concept"]) for e in cleared.get("exclusions", [])}

    dropped_phrases: Dict[str, Dict[str, str]] = {}
    for entry in cleared["concepts"]:
        for phrase in entry["trigger_phrases"]:
            hits = _phrase_documents(documents, entry["concept"], phrase, excluded)
            if len(hits) > max_docs:
                dropped_phrases.setdefault(entry["concept"], {})[phrase] = (
                    f"hub phrase: matches {len(hits)} of {n} documents (more than {max_docs})")
    staged = copy.deepcopy(cleared)
    staged["dropped_phrases"] = dropped_phrases
    overlay = vo.overlay_from_raw(staged)

    by_concept: Dict[str, Dict[str, Dict[str, Any]]] = {}          # concept -> document -> record
    for document in documents:
        for rec in ce.extract_concept_mentions(document, families=families, overlay=overlay):
            by_concept.setdefault(rec["concept"], {})[document["document_id"]] = rec

    rows, dropped, claimed = [], {}, set(baseline_covered)
    for entry in cleared["concepts"]:
        name, status = entry["concept"], entry["status"]
        records = by_concept.get(name, {})
        matched = sorted(records)
        group = groups.get(name, set())
        growth = len([m for m in matched if m not in group])
        passed = sum(1 for m in matched if _evidence_in_body(documents, m, records[m]))
        reasons = []
        if len(matched) > max_docs:
            reasons.append(f"(a) matches {len(matched)} documents (more than {max_docs})")
        if status == vo.STATUS_EXTEND and growth > MAX_GROWTH:
            reasons.append(f"(a) growth {growth} over its existing group (more than {MAX_GROWTH})")
        if status == vo.STATUS_NEW and len(matched) < MIN_NEW_DOCUMENTS:
            reasons.append(f"(b) a NEW concept must link at least {MIN_NEW_DOCUMENTS} documents (links {len(matched)})")
        if passed != len(matched):
            reasons.append(f"(c) evidence phrase missing from the body in {len(matched) - passed} of {len(matched)} documents")
        keep = not reasons
        newly = [m for m in matched if m not in claimed] if keep else []
        if keep:
            claimed |= set(matched)
        else:
            dropped[name] = "; ".join(reasons)
        rows.append({"concept": name, "status": status, "docs": len(matched), "matched": matched, "newly_covered": len(newly),
                     "newly_covered_documents": newly, "growth": growth, "group_size": len(group), "evidence": f"{passed}/{len(matched)}",
                     "phrases_dropped": sorted(dropped_phrases.get(name, {})), "decision": "KEEP" if keep else "DROP", "reasons": reasons})

    covered = set(five_label_covered)
    for name, records in by_concept.items():
        if name not in dropped:                                  # includes concepts kept through the earlier name-family rules
            covered |= set(records)
    all_ids = {d["document_id"] for d in documents}
    return {"rows": rows, "dropped": dropped, "dropped_phrases": dropped_phrases, "coverage_after": len(covered),
            "uncovered": sorted(all_ids - covered), "max_documents_per_concept": max_docs}


def apply_decisions(raw: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(raw)
    out["dropped"] = dict(result["dropped"])
    out["dropped_phrases"] = {k: dict(v) for k, v in result["dropped_phrases"].items()}
    return out


def unexpected_matches(documents: Iterable[Dict[str, Any]], overlay: vo.Overlay, expected: Set[Tuple[str, str, str]]) -> Dict[str, Any]:
    """Phrase matches (concept, phrase, document) that the evidence file does not list, with a snippet; and listed ones that do not match."""
    documents = list(documents)
    found, snippets = set(), {}
    for concept, phrases in overlay.triggers.items():
        for phrase in phrases:
            pattern = ce._compile(phrase)
            for d in documents:
                if (d["document_id"], concept) in overlay.excluded:
                    continue
                text = ce.body_text(d)
                m = pattern.search(text)
                if m:
                    key = (concept, phrase, d["document_id"])
                    found.add(key)
                    snippets[key] = ce._snippet(text, m.start(), m.end())
    unexpected = [{"concept": c, "phrase": p, "doc_id": i, "snippet": snippets[(c, p, i)]} for c, p, i in sorted(found - expected)]
    return {"unexpected": unexpected, "missing": sorted(expected - found)}


def load_expected(path) -> Set[Tuple[str, str, str]]:
    with open(path, encoding="utf-8", newline="") as handle:
        return {(r["concept"], r["trigger_phrase"], r["doc_id"]) for r in csv.DictReader(handle)}


def _uncovered(result: Dict[str, Any], documents) -> List[str]:
    covered = {k for k, v in result["per_document"].items() if v} | {m["document_id"] for m in result["concept_mentions"]}
    return [d["document_id"] for d in documents if d["document_id"] not in covered]


def main() -> None:
    from unittest import mock

    from knowledge_graph.entity_extractor import extract_entities, load_documents
    from knowledge_graph.evaluate_concept_families import concept_groups

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    documents = load_documents()
    with mock.patch.object(ce, "OVERLAY_ENABLED", False):
        before = ce.extract_content(documents)                   # the state before this task: 5 labels + the earlier name families, no exclusions
    baseline = {d["document_id"] for d in documents} - set(_uncovered(before, documents))
    five = {k for k, v in before["per_document"].items() if v}
    nodes = extract_entities(documents)["nodes"] + before["nodes"]
    groups = concept_groups(documents, before["per_document"], nodes)

    overlay_raw = json.loads(vo.OVERLAY_PATH.read_text(encoding="utf-8"))
    result = evaluate(documents, overlay_raw, groups, baseline, five)
    print(f"documents: {len(documents)}; limit per concept: {result['max_documents_per_concept']}; "
          f"with a content concept before: {len(baseline)} (5 labels alone: {len(five)})")
    print(f"{'concept':<44}{'status':<17}{'docs':>5}{'newly':>6}{'growth':>7}{'group':>6}  evidence  decision")
    for r in result["rows"]:
        why = f"  <- {'; '.join(r['reasons'])}" if r["reasons"] else ""
        print(f"{r['concept']:<44}{r['status']:<17}{r['docs']:>5}{r['newly_covered']:>6}{r['growth']:>7}{r['group_size']:>6}  "
              f"{r['evidence']:<8}  {r['decision']}{why}")
    for concept, phrases in result["dropped_phrases"].items():
        for phrase, why in phrases.items():
            print(f"HUB PHRASE dropped: {concept} / {phrase!r}: {why}")
    print(f"documents with a content concept after: {result['coverage_after']} (before: {len(baseline)})")
    print(f"still uncovered ({len(result['uncovered'])}): {result['uncovered']}")
    if "--apply" in sys.argv:
        applied = apply_decisions(overlay_raw, result)
        vo.OVERLAY_PATH.write_text(json.dumps(applied, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print("decisions written to", vo.OVERLAY_PATH)


if __name__ == "__main__":
    main()
