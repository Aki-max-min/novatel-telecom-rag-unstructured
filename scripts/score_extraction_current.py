"""Score the extraction against the AI-labelled gold sheet (human review pending) in three views.

    python scripts/score_extraction_current.py [docs/extraction_gold_sheet_reviewed.csv]

  stale-strict    the sheet's own predicted_concepts (they predate the vocabulary overlay)
  current-strict  predictions regenerated with the CURRENT extractor for the same 20 documents
  current-lenient as current-strict, but predictions in docs/extraction_template_only.json count as correct

Per-label precision, recall, tp, fp, fn; the five content labels pooled; the Concept label separately (not comparable, see knowledge_graph/gold_scoring.py).
Nothing here is validation: the labels were drafted by an AI assistant and no human has reviewed them.
"""

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import gold_scoring as gs  # noqa: E402


def fmt(v):
    return "  n/a" if v is None else f"{v:.3f}"


def show(title, res):
    print(f"\n=== {title} ({res['documents']} documents, {res['predictions']} predictions) ===")
    print(f"{'label':<20}{'precision':>10}{'recall':>8}{'tp':>5}{'fp':>5}{'fn':>5}")
    for label, c in res["per_label"].items():
        print(f"{label:<20}{fmt(c['precision']):>10}{fmt(c['recall']):>8}{c['tp']:>5}{c['fp']:>5}{c['fn']:>5}")
    f = res["five_label"]
    print(f"{'FIVE LABELS POOLED':<20}{fmt(f['precision']):>10}{fmt(f['recall']):>8}{f['tp']:>5}{f['fp']:>5}{f['fn']:>5}")
    c = res["concept"]
    print(f"{'Concept (separate)':<20}{fmt(c['precision']):>10}{fmt(c['recall']):>8}{c['tp']:>5}{c['fp']:>5}{c['fn']:>5}   <- {c['note']}")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else gs.REVIEWED_PATH
    docs = gs.read_reviewed(path)
    template = gs.load_template_only()
    stale = {k: v["predicted"] for k, v in docs.items()}
    current = gs.current_predictions()
    missing = sorted(set(docs) - set(current))
    if missing:
        print("the current extractor's sample does not contain:", missing)
        return 1
    print(f"sheet: {path}\nlabels: drafted and re-checked by an AI assistant; NOT human-reviewed. Template-only list: {len(sum((list(v) for v in template.values()), []))} predictions.")
    show("stale-strict (the sheet's own predictions)", gs.score(docs, stale))
    show("current-strict (current extractor)", gs.score(docs, current))
    show("current-lenient (template-only predictions count as correct)", gs.score(docs, current, template_only=template, lenient=True))
    strict = gs.score(docs, current)
    rows = gs.classify_disagreements(strict["disagreements"], template)
    out = REPO_ROOT / "docs" / "extraction_validation_disagreements.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["doc_id", "kind", "concept", "cause"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    by_cause = {}
    for r in rows:
        by_cause[r["cause"]] = by_cause.get(r["cause"], 0) + 1
    print(f"\ndisagreements of the current extractor by cause (written to {out.name}): {by_cause}")
    changed = [d for d in sorted(docs) if sorted(stale[d]) != sorted(current[d])]
    print(f"\ndocuments whose predictions differ between the sheet and the current extractor: {len(changed)}")
    for d in changed:
        print(f"  {d}: only in sheet {sorted(set(stale[d]) - set(current[d]))}; only now {sorted(set(current[d]) - set(stale[d]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
