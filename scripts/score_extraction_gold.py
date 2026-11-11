"""Score the content extraction against a HUMAN-filled gold sheet (docs/extraction_gold_sheet.csv).

    python scripts/score_extraction_gold.py [path/to/filled.csv]

Prints per-label precision and recall and the list of disagreements. Rows whose correct_concepts is blank are not reviewed and are
skipped (write NONE for "no concept"); with no reviewed row no score is printed. Never fills the sheet.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph.gold_sheet import SHEET_PATH, score_sheet  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SHEET_PATH
    res = score_sheet(path)
    print(f"sheet: {path}")
    print(f"reviewed rows: {res['reviewed_rows']}   not reviewed (correct_concepts blank): {res['unreviewed_rows']}")
    if not res["reviewed_rows"]:
        print("No reviewed row: nothing to score. A human must fill correct_concepts first.")
        return 1
    fmt = lambda v: "n/a" if v is None else f"{v:.3f}"  # noqa: E731
    for label, c in res["per_label"].items():
        print(f"{label:<20} precision {fmt(c['precision'])}  recall {fmt(c['recall'])}   (tp {c['tp']}, fp {c['fp']}, fn {c['fn']})")
    print(f"disagreements: {len(res['disagreements'])}")
    for d in res["disagreements"]:
        print(f"  {d['doc_id']:<28} {d['kind']:<15} {d['concept']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
