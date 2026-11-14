"""Score the content extraction against a filled gold sheet (docs/extraction_gold_sheet.csv is the BLANK template for a human).

    python scripts/score_extraction_gold.py [path/to/filled.csv [path/to/template_only.json]]

Prints per-label precision and recall and the list of disagreements, using the sheet's own predicted_concepts. Rows whose correct_concepts is blank are not
reviewed and are skipped (write NONE for "no concept"); with no reviewed row no score is printed. Never fills the sheet.
With a second argument (a template-only list, e.g. docs/extraction_template_only_v2.json) the lenient five-label figures are printed as well
(predictions on that list count as correct). Without it the output is unchanged. A sheet whose notes say "NOT human-reviewed" is flagged as AI-labelled.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import gold_scoring as gs  # noqa: E402
from knowledge_graph.gold_sheet import SHEET_PATH, is_ai_labelled, label_status, score_sheet  # noqa: E402

WORDS = {7: "seven"}


def status_line(path):
    """The wording of the label status for a sheet; '' for a sheet with no AI-labelled row."""
    status = label_status(path)
    if status["owner_decided"]:
        n = status["owner_decided"]
        return (f"labels: AI-labelled; {WORDS.get(n, n)} rows decided by the project owner (as relayed in chat); "
                f"{status['ai_only']} rows are AI-labelled, not human-reviewed. Not validation.")
    if is_ai_labelled(path):
        return "NOTE: the labels in this sheet were drafted by an AI assistant and are NOT human-reviewed: this is not validation."
    return ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = Path(argv[0]) if argv else SHEET_PATH
    template_path = Path(argv[1]) if len(argv) > 1 else None
    res = score_sheet(path)
    print(f"sheet: {path}")
    line = status_line(path)
    if line:
        print(line)
    print(f"reviewed rows: {res['reviewed_rows']}   not reviewed (correct_concepts blank): {res['unreviewed_rows']}")
    if not res["reviewed_rows"]:
        print("No reviewed row: nothing to score. A human must fill correct_concepts first.")
        return 1
    fmt = lambda v: "n/a" if v is None else f"{v:.3f}"  # noqa: E731
    for label, c in res["per_label"].items():
        print(f"{label:<20} precision {fmt(c['precision'])}  recall {fmt(c['recall'])}   (tp {c['tp']}, fp {c['fp']}, fn {c['fn']})")
    if template_path is not None:
        docs = gs.read_reviewed(path)
        stale = {k: v["predicted"] for k, v in docs.items()}
        template = gs.load_template_only(template_path)
        strict = gs.score(docs, stale)["five_label"]
        lenient = gs.score(docs, stale, template_only=template, lenient=True)["five_label"]
        print(f"five content labels pooled, the sheet's own predictions, template-only list {template_path.name}:")
        print(f"  strict  precision {fmt(strict['precision'])}  recall {fmt(strict['recall'])}   (tp {strict['tp']}, fp {strict['fp']}, fn {strict['fn']})")
        print(f"  lenient precision {fmt(lenient['precision'])}  recall {fmt(lenient['recall'])}   (tp {lenient['tp']}, fp {lenient['fp']}, fn {lenient['fn']})")
    print(f"disagreements: {len(res['disagreements'])}")
    for d in res["disagreements"]:
        print(f"  {d['doc_id']:<28} {d['kind']:<15} {d['concept']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
