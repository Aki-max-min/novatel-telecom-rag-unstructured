"""Human gold sheet for the content extraction (KG fixes 2, step 1).

We PREPARE the sheet; a human fills ``correct_concepts``. Model output is never gold and no human column is ever written here.

* ``select_documents`` - 20 documents by a fixed rule: one from each of the three categories that have no concepts (C11, C12, C24), the
  rest stratified by document type (``TYPE_QUOTAS``), drawn with ``random.Random(SEED)`` over id-sorted candidates.
* ``build_rows`` / ``write_sheet`` - the CSV: doc_id, doc_type, category, text (first 600 characters), predicted_concepts (label:name),
  evidence_phrase_in_text (label:name=phrase, one per prediction, same order), correct_concepts and notes (EMPTY, for a human).
* ``evidence_check`` - every predicted concept's evidence phrase must be present in the document text. It is the extractor's own rule
  applied again, so it is a precision PROXY, not validation: it cannot tell a wrong sense from a right one.
* ``score_sheet`` - once a human has filled ``correct_concepts`` (``NONE`` = no concept; blank = not reviewed): per-label precision, recall
  and the list of disagreements.

    python -m knowledge_graph.gold_sheet                      # (re)write docs/extraction_gold_sheet.csv, print the evidence proxy
    python scripts/score_extraction_gold.py [sheet.csv]       # after a human filled it
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from knowledge_graph.content_extractor import _compile, extract_concept_mentions, extract_document_concepts
from knowledge_graph.entity_extractor import load_documents

REPO_ROOT = Path(__file__).resolve().parent.parent
SHEET_PATH = REPO_ROOT / "docs" / "extraction_gold_sheet.csv"
SEED = 20260611
FORCED_CATEGORIES = ("C11", "C12", "C24")
TYPE_QUOTAS: Dict[str, int] = {"FAQ": 4, "KB": 3, "SOP": 3, "INC": 3, "MAN": 3, "EML": 2, "TRN": 2}
COLUMNS = ["doc_id", "doc_type", "category", "text", "predicted_concepts", "evidence_phrase_in_text", "correct_concepts", "notes"]
TEXT_CHARS = 600
PROXY_LABEL = "precision PROXY, not validation"


def _type_of(document_id: str) -> str:
    return document_id.split("_")[0]


def select_documents(documents: Iterable[Dict[str, Any]], seed: int = SEED) -> List[str]:
    docs = sorted(documents, key=lambda d: d["document_id"])
    rng = random.Random(seed)
    eligible = [d for d in docs if _type_of(d["document_id"]) in TYPE_QUOTAS]
    chosen: List[str] = []
    for category in FORCED_CATEGORIES:
        pool = [d["document_id"] for d in eligible if d["category"] == category and d["document_id"] not in chosen]
        chosen.append(rng.choice(pool))
    for doc_type, quota in TYPE_QUOTAS.items():
        have = sum(1 for i in chosen if _type_of(i) == doc_type)
        pool = [d["document_id"] for d in eligible if _type_of(d["document_id"]) == doc_type and d["document_id"] not in chosen]
        rng.shuffle(pool)
        chosen.extend(pool[: max(0, quota - have)])
    return sorted(chosen)


def _full_text(document: Dict[str, Any]) -> str:
    return (document.get("title") or "") + "\n" + (document.get("content") or "")


def build_rows(documents: Iterable[Dict[str, Any]], seed: int = SEED) -> List[Dict[str, str]]:
    documents = list(documents)
    by_id = {d["document_id"]: d for d in documents}
    rows = []
    for document_id in select_documents(documents, seed):
        document = by_id[document_id]
        records = extract_document_concepts(document) + extract_concept_mentions(document)   # 5 content labels + Concept (body mentions)
        predicted = [f"{r['concept_type']}:{r['concept']}" for r in records]
        evidence = [f"{r['concept_type']}:{r['concept']}={r['evidence_span']}" for r in records]
        rows.append({
            "doc_id": document_id,
            "doc_type": _type_of(document_id),
            "category": document.get("category") or "",
            "text": (document.get("content") or "")[:TEXT_CHARS],
            "predicted_concepts": "; ".join(predicted),
            "evidence_phrase_in_text": " | ".join(evidence),
            "correct_concepts": "",
            "notes": "",
        })
    return rows


def write_sheet(rows: List[Dict[str, str]], path: Path = SHEET_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def evidence_check(documents: Iterable[Dict[str, Any]], records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Pass rate of 'the evidence phrase is present in the document text' over every prediction (a precision PROXY)."""
    documents = list(documents)
    by_id = {d["document_id"]: d for d in documents}
    if records is None:
        records = [r for d in documents for r in extract_document_concepts(d) + extract_concept_mentions(d)]
    failures = []
    for r in records:
        text = _full_text(by_id[r["document_id"]])
        phrase = r.get("evidence_span") or (r["matched_terms"][0] if r.get("matched_terms") else "")
        if not phrase or not _compile(phrase).search(text):
            failures.append({"document_id": r["document_id"], "concept": f"{r['concept_type']}:{r['concept']}", "phrase": phrase})
    total = len(records)
    return {"label": PROXY_LABEL, "predictions": total, "passed": total - len(failures),
            "rate": (total - len(failures)) / total if total else None, "failures": failures}


def _labels(cell: str) -> List[str]:
    cell = (cell or "").strip()
    if not cell or cell.upper() == "NONE":
        return []
    return [part.strip() for part in cell.split(";") if part.strip()]


def score_sheet(path: Path) -> Dict[str, Any]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    disagreements = []
    reviewed = 0
    for row in rows:
        if not (row.get("correct_concepts") or "").strip():
            continue
        reviewed += 1
        predicted, correct = set(_labels(row["predicted_concepts"])), set(_labels(row["correct_concepts"]))
        for concept in sorted(predicted | correct):
            label = concept.split(":", 1)[0]
            if concept in predicted and concept in correct:
                counts[label]["tp"] += 1
            elif concept in predicted:
                counts[label]["fp"] += 1
                disagreements.append({"doc_id": row["doc_id"], "kind": "false_positive", "concept": concept})
            else:
                counts[label]["fn"] += 1
                disagreements.append({"doc_id": row["doc_id"], "kind": "false_negative", "concept": concept})
    per_label = {}
    for label, c in sorted(counts.items()):
        per_label[label] = dict(c, precision=(c["tp"] / (c["tp"] + c["fp"])) if c["tp"] + c["fp"] else None,
                                recall=(c["tp"] / (c["tp"] + c["fn"])) if c["tp"] + c["fn"] else None)
    return {"reviewed_rows": reviewed, "unreviewed_rows": len(rows) - reviewed, "per_label": per_label, "disagreements": disagreements}


def label_status(path: Path) -> Dict[str, int]:
    """Rows decided by the project owner (notes start a "HUMAN DECISION") and rows that are AI-labelled only (notes say NOT human-reviewed)."""
    owner = ai_only = 0
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            notes = row.get("notes") or ""
            if "HUMAN DECISION" in notes:
                owner += 1
            elif "NOT human-reviewed" in notes:
                ai_only += 1
    return {"owner_decided": owner, "ai_only": ai_only}


def is_ai_labelled(path: Path) -> bool:
    """True when at least one row's labels were NOT reviewed by a human (drafted by an AI assistant)."""
    return label_status(path)["ai_only"] > 0


def main() -> None:
    documents = load_documents()
    rows = build_rows(documents)
    path = write_sheet(rows)
    check = evidence_check(documents)
    print(f"written: {path} ({len(rows)} documents, seed {SEED}); human columns left EMPTY")
    print(f"evidence check ({check['label']}): {check['passed']}/{check['predictions']} = {check['rate']:.4f}; failures: {len(check['failures'])}")


if __name__ == "__main__":
    main()
