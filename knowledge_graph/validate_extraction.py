"""Validation harness for the curated-dictionary content extraction.

Takes a stratified sample of 20 documents across document types, lists every
concept the extractor produced for them, and writes a gold-label template for a
human to fill in. Once the template is filled, the same script computes real
Precision / Recall / F1 against those labels.

Two things this deliberately does **not** do:

* It does not invent labels. Until a human fills ``is_correct``, no true
  precision figure exists and none is printed.
* It does not pretend an automatic check can measure precision. The extractor is
  a dictionary, so "does the trigger appear in the text?" is the extractor's own
  rule - asking it again is circular and would return 1.0 by construction.

What it *can* check automatically:

* **Evidence integrity** - re-scan each document with a freshly compiled pattern
  and confirm every recorded ``matched_terms`` entry really is present. This
  catches stale outputs, bad offsets and evidence-recording bugs. It can fail.
* **Provisional precision** - restricted to predictions triggered by a
  multi-word phrase (e.g. "self-care portal", "video kyc"), minus any whose
  evidence window carries a negation or hypothetical cue. That negation screen
  is what lets the number fall below 1.0; without it the check would just be
  the extractor's own rule. Reported as an explicit upper-bound proxy, never as
  the real number.

Usage::

    python -m knowledge_graph.validate_extraction
    python -m knowledge_graph.validate_extraction --template path/to/filled.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from knowledge_graph.content_extractor import (
    CONCEPT_DICTIONARY,
    extract_document_concepts,
)
from knowledge_graph.entity_extractor import OUTPUT_DIR, load_documents

SAMPLE_SIZE = 20
TEMPLATE_PATH = OUTPUT_DIR / "extraction_gold_template.csv"
REPORT_PATH = OUTPUT_DIR / "extraction_validation.json"

#: Blank rows appended per sampled document so missed concepts (false negatives)
#: can be written straight into the template.
BLANK_FN_ROWS_PER_DOCUMENT = 2

CSV_COLUMNS = [
    "document_id",
    "document_type",
    "concept",
    "type",
    "matched_terms",
    "evidence",
    "predicted",
    "is_correct",
    "notes",
]


def stratified_sample(
    documents: Sequence[Dict[str, Any]], size: int = SAMPLE_SIZE
) -> List[Dict[str, Any]]:
    """Deterministic stratified sample across document_type.

    Proportional allocation with largest-remainder, then evenly spaced picks
    within each type (documents sorted by id). No RNG, so the sample is the same
    on every machine and every run.
    """
    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for document in documents:
        by_type[document.get("document_type", "")].append(document)
    for group in by_type.values():
        group.sort(key=lambda document: document["document_id"])

    total = len(documents)
    exact = {name: len(group) * size / total for name, group in by_type.items()}
    allocation = {name: min(int(value), len(by_type[name])) for name, value in exact.items()}

    # Every type present in the corpus gets at least one slot where possible.
    for name in by_type:
        if allocation[name] == 0:
            allocation[name] = 1

    def trim_or_grow(current: Dict[str, int]) -> Dict[str, int]:
        while sum(current.values()) > size:
            # Remove from the type that is most over its exact share.
            name = max(
                (n for n in current if current[n] > 1),
                key=lambda n: (current[n] - exact[n], n),
            )
            current[name] -= 1
        while sum(current.values()) < size:
            name = min(
                (n for n in current if current[n] < len(by_type[n])),
                key=lambda n: (current[n] - exact[n], n),
            )
            current[name] += 1
        return current

    allocation = trim_or_grow(allocation)

    sample: List[Dict[str, Any]] = []
    for name in sorted(by_type):
        group = by_type[name]
        take = allocation[name]
        if take <= 0:
            continue
        # Evenly spaced indices so the pick is not just the alphabetical head.
        step = len(group) / take
        indices = sorted({min(len(group) - 1, int(i * step)) for i in range(take)})
        while len(indices) < take:
            for candidate in range(len(group)):
                if candidate not in indices:
                    indices.append(candidate)
                    break
            indices = sorted(set(indices))
        sample.extend(group[i] for i in indices[:take])

    sample.sort(key=lambda document: document["document_id"])
    return sample


def _boundary_pattern(phrase: str) -> re.Pattern:
    """Independently recompiled matcher, mirroring the extractor's rule."""
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])", re.IGNORECASE
    )


def verify_evidence(document: Dict[str, Any], record: Dict[str, Any]) -> bool:
    """Re-scan the document and confirm every recorded trigger really matches."""
    haystack = f"{document.get('title', '')}\n{document.get('content', '')}"
    return all(
        _boundary_pattern(term).search(haystack) is not None
        for term in record["matched_terms"]
    )


def is_multiword(terms: Sequence[str]) -> bool:
    """True when at least one firing trigger is a multi-word phrase."""
    return any(len(term.split()) > 1 for term in terms)


#: Cues that a match may be negated, hypothetical or contrastive - i.e. the
#: concept is named but not actually asserted of this document's subject.
#: This is what makes the provisional check falsifiable: without it, "does the
#: trigger appear?" is the extractor's own rule and would always return 1.0.
CONTEXT_FLAGS: Tuple[re.Pattern, ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bnot\b",
        r"\bno longer\b",
        r"\bcannot\b",
        r"\bcan't\b",
        r"\bwithout\b",
        r"\bunable\b",
        r"\binstead of\b",
        r"\brather than\b",
        r"\bunlike\b",
        r"\bexcept\b",
        r"\bout of scope\b",
        r"\bdo not\b",
        r"\bdon't\b",
        r"\bnever\b",
        r"\bif you (?:don't|do not|no longer)\b",
    )
)


def context_flags(evidence: str) -> List[str]:
    """Negation / hypothetical cues in the evidence window, if any."""
    return [
        pattern.pattern
        for pattern in CONTEXT_FLAGS
        if pattern.search(evidence or "")
    ]


def collect_predictions(sample: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every (document, concept) the extractor produced for the sample."""
    rows: List[Dict[str, Any]] = []
    for document in sample:
        for record in extract_document_concepts(document):
            rows.append(
                {
                    "document_id": document["document_id"],
                    "document_type": document.get("document_type", ""),
                    "concept": record["concept"],
                    "type": record["concept_type"],
                    "matched_terms": ", ".join(record["matched_terms"]),
                    "evidence": record["evidence"],
                    "predicted": 1,
                    "is_correct": "",
                    "notes": "",
                    "_multiword": is_multiword(record["matched_terms"]),
                    "_evidence_ok": verify_evidence(document, record),
                    "_context_flags": context_flags(record["evidence"]),
                }
            )
    return rows


def write_template(
    rows: Sequence[Dict[str, Any]],
    sample: Sequence[Dict[str, Any]],
    path: Path = TEMPLATE_PATH,
) -> Path:
    """Write the gold-label CSV, with blank rows for false negatives."""
    path.parent.mkdir(parents=True, exist_ok=True)
    by_document: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_document[row["document_id"]].append(row)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for document in sample:
            document_id = document["document_id"]
            for row in by_document.get(document_id, []):
                writer.writerow({column: row[column] for column in CSV_COLUMNS})
            # Blank rows: fill concept + type + is_correct=1 to record a concept
            # the extractor MISSED (a false negative). Leave untouched otherwise.
            for _ in range(BLANK_FN_ROWS_PER_DOCUMENT):
                writer.writerow(
                    {
                        "document_id": document_id,
                        "document_type": document.get("document_type", ""),
                        "concept": "",
                        "type": "",
                        "matched_terms": "",
                        "evidence": "",
                        "predicted": 0,
                        "is_correct": "",
                        "notes": "add a MISSED concept here (predicted=0)",
                    }
                )
    return path


def read_labels(path: Path) -> Tuple[List[Dict[str, str]], bool]:
    """Read a template back. Returns (rows, any_labels_filled)."""
    if not path.exists():
        return [], False
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    filled = any((row.get("is_correct") or "").strip() for row in rows)
    return rows, filled


def _as_flag(value: Optional[str]) -> Optional[bool]:
    text = (value or "").strip().lower()
    if text in {"1", "y", "yes", "true", "t"}:
        return True
    if text in {"0", "n", "no", "false", "f"}:
        return False
    return None


def score_labelled(rows: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    """Real Precision / Recall / F1 from a filled template."""
    true_positives = false_positives = false_negatives = unlabelled = 0
    for row in rows:
        predicted = (row.get("predicted") or "").strip() == "1"
        flag = _as_flag(row.get("is_correct"))
        concept = (row.get("concept") or "").strip()
        if predicted:
            if flag is None:
                unlabelled += 1
            elif flag:
                true_positives += 1
            else:
                false_positives += 1
        else:
            # A non-predicted row only counts once a concept has been written in.
            if concept and flag is not False:
                false_negatives += 1

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives)
        else 0.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives)
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    )
    return {
        "provisional": False,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "unlabelled_predictions": unlabelled,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def score_provisional(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Provisional precision on the auto-verifiable (multi-word trigger) subset."""
    total = len(rows)
    evidence_ok = sum(1 for row in rows if row["_evidence_ok"])
    subset = [row for row in rows if row["_multiword"]]
    clearly_correct = [
        row for row in subset if row["_evidence_ok"] and not row["_context_flags"]
    ]
    needs_review = [row for row in subset if row["_context_flags"]]
    flagged_all = [row for row in rows if row["_context_flags"]]
    provisional_precision = (len(clearly_correct) / len(subset)) if subset else 0.0
    return {
        "provisional": True,
        "predictions_total": total,
        "evidence_integrity_ok": evidence_ok,
        "evidence_integrity_rate": round(evidence_ok / total, 4) if total else 0.0,
        "auto_verifiable_subset": len(subset),
        "auto_verifiable_share": round(len(subset) / total, 4) if total else 0.0,
        "clearly_correct": len(clearly_correct),
        "flagged_for_review_in_subset": len(needs_review),
        "flagged_for_review_all": len(flagged_all),
        "flagged_examples": [
            {
                "document_id": row["document_id"],
                "concept": f"{row['type']}::{row['concept']}",
                "cues": row["_context_flags"],
                "evidence": row["evidence"][:160],
            }
            for row in flagged_all[:5]
        ],
        "precision": round(provisional_precision, 4),
        "recall": None,
        "f1": None,
        "meaning": (
            "Provisional precision = clearly-correct / auto-verifiable, where auto-verifiable "
            "means the prediction fired on a MULTI-WORD phrase that re-matches the document on "
            "an independent re-scan, and clearly-correct additionally means the evidence window "
            "carries no negation or hypothetical cue (not, without, instead of, no longer, ...). "
            "The negation screen is what makes this falsifiable: a pure does-the-trigger-appear "
            "check would be the extractor's own rule and would return 1.0 by construction. "
            "It is still an UPPER BOUND, not measured precision - it cannot see sense errors, "
            "and single-word triggers (otp, kyc, recharge, ont, ...) are excluded precisely "
            "because those are the ambiguous cases. Recall cannot be estimated at all without "
            "human labels, so it is reported as n/a."
        ),
    }


def summarise_sample(sample: Sequence[Dict[str, Any]], rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_type = Counter(document.get("document_type", "") for document in sample)
    concepts_by_type = Counter(row["type"] for row in rows)
    documents_with_concepts = len({row["document_id"] for row in rows})
    return {
        "sample_size": len(sample),
        "sample_document_ids": [document["document_id"] for document in sample],
        "sample_by_document_type": dict(sorted(by_type.items())),
        "documents_with_at_least_one_concept": documents_with_concepts,
        "predictions_total": len(rows),
        "predictions_by_concept_type": dict(sorted(concepts_by_type.items())),
        "dictionary_concepts_declared": sum(
            len(concepts) for concepts in CONCEPT_DICTIONARY.values()
        ),
    }


def run(template_path: Path = TEMPLATE_PATH) -> Dict[str, Any]:
    documents = load_documents()
    sample = stratified_sample(documents)
    rows = collect_predictions(sample)

    existing_rows, filled = read_labels(template_path)
    if filled:
        scores = score_labelled(existing_rows)
        written: Optional[Path] = None
    else:
        scores = score_provisional(rows)
        written = write_template(rows, sample, template_path)

    report = {
        "sample": summarise_sample(sample, rows),
        "scores": scores,
        "template_path": str(template_path),
        "template_filled": filled,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    report["_template_written"] = str(written) if written else None
    return report


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)


def _force_utf8_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main() -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(description="Validate content extraction.")
    parser.add_argument("--template", type=Path, default=TEMPLATE_PATH)
    args = parser.parse_args()

    report = run(args.template)
    sample = report["sample"]
    scores = report["scores"]

    print("=" * 72)
    print("ENTITY-EXTRACTION VALIDATION")
    print("=" * 72)
    print(f"stratified sample      : {sample['sample_size']} documents")
    print(f"  by document_type     : {sample['sample_by_document_type']}")
    print(f"  with >=1 concept     : {sample['documents_with_at_least_one_concept']}")
    print(f"predictions            : {sample['predictions_total']}")
    print(f"  by concept type      : {sample['predictions_by_concept_type']}")
    print()

    if scores["provisional"]:
        print("template not filled in yet -> PROVISIONAL numbers only")
        print(f"  evidence integrity   : {scores['evidence_integrity_ok']}/{scores['predictions_total']} "
              f"({scores['evidence_integrity_rate']:.4f}) triggers re-match on an independent re-scan")
        print(f"  auto-verifiable      : {scores['auto_verifiable_subset']} predictions "
              f"({scores['auto_verifiable_share']:.4f} of total) fired on a multi-word phrase")
        print(f"  flagged for review   : {scores['flagged_for_review_all']} of {scores['predictions_total']} "
              f"carry a negation/hypothetical cue ({scores['flagged_for_review_in_subset']} inside the subset)")
        print(f"  provisional precision: {scores['precision']:.4f} "
              f"({scores['clearly_correct']}/{scores['auto_verifiable_subset']} clearly correct)")
        print(f"  recall / f1          : n/a (needs human labels)")
        print()
        print(f"  {scores['meaning']}")
        if report["_template_written"]:
            print()
            print(f"gold-label template written: {report['_template_written']}")
            print("  Fill the is_correct column (1 = correct, 0 = wrong) and add any")
            print("  concepts the extractor missed on the blank predicted=0 rows, then")
            print("  re-run this script for real Precision / Recall / F1.")
    else:
        print("template filled -> MEASURED numbers")
        print(f"  true positives       : {scores['true_positives']}")
        print(f"  false positives      : {scores['false_positives']}")
        print(f"  false negatives      : {scores['false_negatives']}")
        print(f"  unlabelled predictions: {scores['unlabelled_predictions']}")
        print(f"  precision            : {scores['precision']:.4f}")
        print(f"  recall               : {scores['recall']:.4f}")
        print(f"  f1                   : {scores['f1']:.4f}")

    print()
    print(f"report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
