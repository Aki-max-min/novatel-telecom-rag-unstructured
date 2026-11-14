"""Scoring of the AI-labelled gold sheet in three views (KG fixes 5, step 2).

The reviewed sheet (docs/extraction_gold_sheet_reviewed.csv) was drafted and re-checked by an AI assistant (two passes); it was NOT reviewed by a human and nothing
here calls it validated. ``correct_concepts`` = the concepts that are part of the document's specific content (sentences copied into every document of a type do not
count); ``NONE`` = no concept; a blank cell = not reviewed (skipped).

Views (see scripts/score_extraction_current.py):
  stale-strict    the sheet's own ``predicted_concepts`` (they predate the vocabulary overlay) against ``correct_concepts``
  current-strict  predictions regenerated with the CURRENT extractor (``gold_sheet.build_rows``) for the same documents
  current-lenient as current-strict, but predictions listed in docs/extraction_template_only.json (template boilerplate or a weak passing mention) count as correct

Pooled over the five content labels: Service, Channel, VerificationMethod, Requirement, Location. The ``Concept`` label is reported separately and is NOT comparable:
the gold lists each document's main-topic concept, while the extractor only emits the concepts of the vocabulary overlay and of two name families.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from knowledge_graph.gold_sheet import _labels, build_rows
from knowledge_graph.entity_extractor import load_documents

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEWED_PATH = REPO_ROOT / "docs" / "extraction_gold_sheet_reviewed.csv"
TEMPLATE_ONLY_PATH = REPO_ROOT / "docs" / "extraction_template_only.json"
LABELS_FIVE = ("Service", "Channel", "VerificationMethod", "Requirement", "Location")
CONCEPT_NOTE = ("Concept is not comparable: the gold lists each document's main-topic concept; the extractor only emits the concepts of the "
                "vocabulary overlay and of the two name families")


def read_reviewed(path: Path = REVIEWED_PATH) -> Dict[str, Dict[str, Any]]:
    """{doc_id: {"predicted": [...], "correct": [...]}} for the REVIEWED rows (blank correct_concepts are skipped)."""
    out: Dict[str, Dict[str, Any]] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not (row.get("correct_concepts") or "").strip():
                continue
            out[row["doc_id"]] = {"predicted": _labels(row["predicted_concepts"]), "correct": _labels(row["correct_concepts"]),
                                  "notes": row.get("notes", "")}
    return out


def load_template_only(path: Path = TEMPLATE_ONLY_PATH) -> Dict[str, Set[str]]:
    with Path(path).open(encoding="utf-8") as handle:
        return {doc: set(entries) for doc, entries in json.load(handle)["template_only"].items()}


def current_predictions(documents: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[str]]:
    """Predictions of the CURRENT extractor for the sheet's documents (``gold_sheet.build_rows``: same selection rule and seed)."""
    rows = build_rows(documents if documents is not None else load_documents())
    return {r["doc_id"]: _labels(r["predicted_concepts"]) for r in rows}


def _rates(c: Dict[str, int]) -> Dict[str, Any]:
    out = dict(c)
    out["precision"] = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None
    out["recall"] = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None
    return out


def score(docs: Dict[str, Dict[str, Any]], predictions: Dict[str, Iterable[str]], template_only: Optional[Dict[str, Set[str]]] = None,
          lenient: bool = False) -> Dict[str, Any]:
    """Strict: a prediction is a true positive iff it is in ``correct``. Lenient: predictions listed in ``template_only`` are added to the correct set first
    (only if the extractor predicted them), so they count as true positives and the recall denominator grows with them."""
    counts: Dict[str, Dict[str, int]] = {}
    disagreements = []
    for doc_id in sorted(docs):
        correct = set(docs[doc_id]["correct"])
        predicted = set(predictions.get(doc_id, []))
        if lenient and template_only:
            correct |= (template_only.get(doc_id, set()) & predicted)
        for concept in sorted(predicted | correct):
            label = concept.split(":", 1)[0]
            c = counts.setdefault(label, {"tp": 0, "fp": 0, "fn": 0})
            if concept in predicted and concept in correct:
                c["tp"] += 1
            elif concept in predicted:
                c["fp"] += 1
                disagreements.append({"doc_id": doc_id, "kind": "false_positive", "concept": concept})
            else:
                c["fn"] += 1
                disagreements.append({"doc_id": doc_id, "kind": "false_negative", "concept": concept})
    per_label = {label: _rates(c) for label, c in sorted(counts.items()) if label != "Concept"}
    pooled = {"tp": 0, "fp": 0, "fn": 0}
    for label in LABELS_FIVE:
        for key in pooled:
            pooled[key] += counts.get(label, {}).get(key, 0)
    concept = _rates(counts.get("Concept", {"tp": 0, "fp": 0, "fn": 0}))
    concept["note"] = CONCEPT_NOTE
    return {"per_label": per_label, "five_label": _rates(pooled), "concept": concept, "disagreements": disagreements,
            "documents": len(docs), "predictions": sum(len(set(predictions.get(d, []))) for d in docs)}
