"""
KG fixes 6 (tests first): the v2 extraction validation. Seven borderline rows were decided by the project owner (as relayed in chat); the other 13 rows stay
AI-labelled and are NOT human-reviewed. The v1 files are never edited; v2 sits beside them. Scripts take an optional template-only path as a second argument.
"""

import contextlib
import csv
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import gold_scoring as gs  # noqa: E402
from knowledge_graph import gold_sheet  # noqa: E402

DOCS = REPO_ROOT / "docs"
V1_SHEET, V1_TEMPLATE = DOCS / "extraction_gold_sheet_reviewed.csv", DOCS / "extraction_template_only.json"
V2_SHEET, V2_TEMPLATE = DOCS / "extraction_gold_sheet_reviewed_v2.csv", DOCS / "extraction_template_only_v2.json"
OWNER_ROWS = {"EML_008", "INC_C08_INC_2026_0211", "INC_C25_INC_2026_0179", "MAN_APP_001", "SOP_C25_FTTH_FAULT_HANDLING", "TRN_002", "TRN_004"}


def rows(path):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {r["doc_id"]: r for r in csv.DictReader(handle)}


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(module, argv, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = module.main(argv, **kwargs)
    return code, buf.getvalue()


class TestV2Files(unittest.TestCase):

    def test_v2_differs_from_v1_only_as_the_owner_decided(self):
        v1, v2 = rows(V1_SHEET), rows(V2_SHEET)
        self.assertEqual(sorted(v1), sorted(v2))
        changed_notes = {d for d in v1 if v1[d]["notes"] != v2[d]["notes"]}
        self.assertEqual(changed_notes, OWNER_ROWS)
        for d in v1:
            for col in ("doc_id", "doc_type", "category", "text", "predicted_concepts", "evidence_phrase_in_text"):
                self.assertEqual(v1[d][col], v2[d][col], (d, col))
        changed_labels = {d for d in v1 if v1[d]["correct_concepts"] != v2[d]["correct_concepts"]}
        self.assertEqual(changed_labels, {"INC_C25_INC_2026_0179", "SOP_C25_FTTH_FAULT_HANDLING"})
        for d in changed_labels:
            self.assertEqual(set(v1[d]["correct_concepts"].split("; ")) - set(v2[d]["correct_concepts"].split("; ")),
                             {"Service:Broadband/FTTH Installation"})
            self.assertEqual(set(v2[d]["correct_concepts"].split("; ")) - set(v1[d]["correct_concepts"].split("; ")), set())

    def test_v2_template_list_is_v1_minus_three_entries(self):
        t1 = json.loads(V1_TEMPLATE.read_text(encoding="utf-8"))["template_only"]
        t2 = json.loads(V2_TEMPLATE.read_text(encoding="utf-8"))["template_only"]
        removed = {(d, e) for d in t1 for e in t1[d] if e not in t2.get(d, [])}
        self.assertEqual(removed, {("TRN_002", "Service:Complaint Registration"), ("MAN_APP_001", "Service:Mobile Number Update"),
                                   ("INC_C08_INC_2026_0211", "Channel:My NovaTel App")})
        self.assertEqual(sum(len(v) for v in t2.values()), 19)
        self.assertEqual({d: v for d, v in t2.items() if d in t1 and set(v) <= set(t1[d])}, t2)       # nothing added

    def test_status_wording_seven_owner_rows_and_thirteen_ai_rows(self):
        status = gold_sheet.label_status(V2_SHEET)
        self.assertEqual(status, {"owner_decided": 7, "ai_only": 13})
        self.assertEqual(gold_sheet.label_status(V1_SHEET), {"owner_decided": 0, "ai_only": 20})
        self.assertTrue(gold_sheet.is_ai_labelled(V2_SHEET))                                          # 13 rows are still AI-only
        self.assertEqual(sum("HUMAN DECISION (owner, 2026-11-14, as relayed in chat)" in r["notes"] for r in rows(V2_SHEET).values()), 7)

    def test_the_v1_files_are_untouched_and_still_score_as_before(self):
        docs = gs.read_reviewed(V1_SHEET)
        res = gs.score(docs, gs.current_predictions())["five_label"]
        self.assertEqual((res["tp"], res["fp"], res["fn"]), (27, 25, 2))


class TestV2Scores(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.docs = gs.read_reviewed(V2_SHEET)
        cls.tmpl = gs.load_template_only(V2_TEMPLATE)
        cls.stale = {k: v["predicted"] for k, v in cls.docs.items()}
        cls.current = gs.current_predictions()

    def five(self, res):
        f = res["five_label"]
        return (f["tp"], f["fp"], f["fn"], round(f["precision"], 3), round(f["recall"], 3))

    def test_stale_strict(self):
        self.assertEqual(self.five(gs.score(self.docs, self.stale)), (25, 27, 2, 0.481, 0.926))

    def test_current_strict(self):
        self.assertEqual(self.five(gs.score(self.docs, self.current)), (25, 27, 2, 0.481, 0.926))

    def test_current_lenient(self):
        self.assertEqual(self.five(gs.score(self.docs, self.current, template_only=self.tmpl, lenient=True)), (44, 8, 2, 0.846, 0.957))

    def test_per_label_strict(self):
        pl = gs.score(self.docs, self.current)["per_label"]
        self.assertEqual((pl["Service"]["tp"], pl["Service"]["fp"], pl["Service"]["fn"]), (14, 13, 0))
        self.assertEqual((pl["Channel"]["tp"], pl["Channel"]["fp"], pl["Channel"]["fn"]), (2, 7, 2))
        self.assertAlmostEqual(pl["Channel"]["precision"], 0.222, places=3)
        self.assertEqual((pl["VerificationMethod"]["tp"], pl["VerificationMethod"]["fp"]), (6, 7))


class TestV2Causes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.docs = gs.read_reviewed(V2_SHEET)
        cls.tmpl = gs.load_template_only(V2_TEMPLATE)
        cls.res = gs.score(cls.docs, gs.current_predictions())
        cls.rows = gs.classify_disagreements(cls.res["disagreements"], cls.tmpl)

    def by_cause(self):
        counts = {}
        for r in self.rows:
            if r["concept"].split(":")[0] in gs.LABELS_FIVE:
                counts[r["cause"]] = counts.get(r["cause"], 0) + 1
        return counts

    def test_counts_per_cause_v2(self):
        self.assertEqual(self.by_cause(), {"template sentence": 19, "wrong sense": 6, "metadata-header echo": 1, "weak passing mention": 1,
                                           "vocabulary gap": 2})
        self.assertEqual([r for r in self.rows if r["cause"] == "unclassified"], [])

    def test_the_owner_decisions_are_wrong_sense(self):
        wrong = {(r["doc_id"], r["concept"]) for r in self.rows if r["cause"] == "wrong sense"}
        self.assertEqual(wrong, {("INC_C05_INC_2026_0171", "Service:Complaint Registration"), ("TRN_002", "Service:Complaint Registration"),
                                 ("MAN_APP_001", "Service:Mobile Number Update"),
                                 ("INC_C25_INC_2026_0179", "Service:Broadband/FTTH Installation"),
                                 ("SOP_C25_FTTH_FAULT_HANDLING", "Service:Broadband/FTTH Installation"),
                                 ("INC_C08_INC_2026_0211", "Channel:My NovaTel App")})

    def test_the_same_prediction_is_a_weak_mention_when_the_v1_list_has_it_and_wrong_sense_when_it_does_not(self):
        v1 = gs.load_template_only(V1_TEMPLATE)
        res1 = gs.score(gs.read_reviewed(V1_SHEET), gs.current_predictions())
        key = ("INC_C08_INC_2026_0211", "Channel:My NovaTel App")
        cause_v1 = {(r["doc_id"], r["concept"]): r["cause"] for r in gs.classify_disagreements(res1["disagreements"], v1)}[key]
        cause_v2 = {(r["doc_id"], r["concept"]): r["cause"] for r in self.rows}[key]
        self.assertEqual((cause_v1, cause_v2), ("weak passing mention", "wrong sense"))

    def test_disagreements_path_keeps_the_v1_file_name_for_v1_and_a_new_name_for_v2(self):
        self.assertEqual(gs.disagreements_path(V1_SHEET), DOCS / "extraction_validation_disagreements.csv")
        self.assertEqual(gs.disagreements_path(V2_SHEET), DOCS / "extraction_validation_disagreements_reviewed_v2.csv")


class TestScriptsTakeAnOptionalTemplatePath(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.current = load_script("score_extraction_current")
        cls.gold = load_script("score_extraction_gold")

    def test_current_script_defaults_are_unchanged(self):
        code, out = run_main(self.current, [], write_csv=False)
        self.assertEqual(code, 0)
        self.assertIn("0.519", out)
        self.assertIn("0.942", out)

    def test_current_script_with_v2_sheet_and_v2_template(self):
        code, out = run_main(self.current, [str(V2_SHEET), str(V2_TEMPLATE)], write_csv=False)
        self.assertEqual(code, 0)
        self.assertIn("0.481", out)
        self.assertIn("0.926", out)
        self.assertIn("0.846", out)
        self.assertIn("0.957", out)
        self.assertIn("seven rows decided by the project owner", out)
        self.assertIn("13 rows are AI-labelled, not human-reviewed", out)
        self.assertNotIn("validated by", out)

    def test_the_template_argument_alone_changes_the_lenient_view(self):
        _, out_v1_template = run_main(self.current, [str(V2_SHEET)], write_csv=False)            # v2 sheet, default (v1) template
        self.assertIn("0.481", out_v1_template)
        self.assertNotIn("0.846", out_v1_template)

    def test_gold_script_defaults_and_template_argument(self):
        code, out = run_main(self.gold, [str(V1_SHEET)])
        self.assertEqual(code, 0)
        self.assertIn("NOT human-reviewed", out)
        self.assertNotIn("lenient", out)
        code, out = run_main(self.gold, [str(V2_SHEET), str(V2_TEMPLATE)])
        self.assertEqual(code, 0)
        self.assertIn("seven rows decided by the project owner", out)
        self.assertIn("lenient", out)
        self.assertIn("0.846", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
