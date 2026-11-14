"""
KG fixes 5, step 2 (tests first): scoring the AI-labelled (human review pending) gold sheet in three views.
  stale-strict   : the sheet's own predicted_concepts (they predate the vocabulary overlay) against correct_concepts
  current-strict : predictions regenerated with the CURRENT extractor for the same documents, against correct_concepts
  current-lenient: as current-strict, but predictions listed in the template-only file count as correct
Per label and pooled over the five content labels (Service, Channel, VerificationMethod, Requirement, Location). The Concept label is reported
separately: it is not comparable (the gold lists each document's main-topic concept; the extractor only emits overlay concepts).
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import gold_scoring as gs  # noqa: E402

COLUMNS = ["doc_id", "doc_type", "category", "text", "predicted_concepts", "evidence_phrase_in_text", "correct_concepts", "notes"]
REVIEWED = REPO_ROOT / "docs" / "extraction_gold_sheet_reviewed.csv"
TEMPLATE = REPO_ROOT / "docs" / "extraction_template_only.json"


def sheet(d, rows):
    p = Path(d) / "sheet.csv"
    with p.open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=COLUMNS)
        w.writeheader()
        for doc, pred, correct in rows:
            w.writerow({"doc_id": doc, "doc_type": "KB", "category": "C01", "text": "t", "predicted_concepts": pred,
                        "evidence_phrase_in_text": "", "correct_concepts": correct, "notes": ""})
    return p


def template(d, mapping):
    p = Path(d) / "template.json"
    p.write_text(json.dumps({"description": "x", "template_only": mapping}), encoding="utf-8")
    return p


class TestScoring(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        # D1: OTP is template boilerplate; Refund is correct; the gold also has the main-topic Concept
        # D2: perfect; D3: gold says NONE, predicted a template OTP; D4: unreviewed (blank) and must be skipped
        self.path = sheet(d, [
            ("D1", "Service:Refund; VerificationMethod:OTP", "Service:Refund; Concept:Billing & Invoices"),
            ("D2", "Channel:IVR", "Channel:IVR"),
            ("D3", "VerificationMethod:OTP", "NONE"),
            ("D4", "Service:Refund", ""),
        ])
        self.template = template(d, {"D1": ["VerificationMethod:OTP"], "D3": ["VerificationMethod:OTP"], "D2": ["Channel:Never Predicted"]})
        self.docs = gs.read_reviewed(self.path)
        self.tmpl = gs.load_template_only(self.template)

    def tearDown(self):
        self.tmp.cleanup()

    def stale(self):
        return {k: v["predicted"] for k, v in self.docs.items()}

    def test_reading_skips_unreviewed_rows_and_parses_none(self):
        self.assertEqual(sorted(self.docs), ["D1", "D2", "D3"])
        self.assertEqual(self.docs["D3"]["correct"], [])
        self.assertEqual(gs.load_template_only(self.template)["D1"], {"VerificationMethod:OTP"})

    def test_strict_counts_per_label(self):
        res = gs.score(self.docs, self.stale())
        svc = res["per_label"]["Service"]
        self.assertEqual((svc["tp"], svc["fp"], svc["fn"]), (1, 0, 0))
        otp = res["per_label"]["VerificationMethod"]
        self.assertEqual((otp["tp"], otp["fp"], otp["fn"]), (0, 2, 0))
        self.assertEqual((otp["precision"], otp["recall"]), (0.0, None))
        ch = res["per_label"]["Channel"]
        self.assertEqual((ch["tp"], ch["fp"], ch["fn"]), (1, 0, 0))

    def test_five_label_pool_excludes_concept(self):
        res = gs.score(self.docs, self.stale())
        five = res["five_label"]
        self.assertEqual((five["tp"], five["fp"], five["fn"]), (2, 2, 0))
        self.assertEqual(five["precision"], 0.5)
        self.assertEqual(five["recall"], 1.0)
        self.assertNotIn("Concept", gs.LABELS_FIVE)
        self.assertEqual(sorted(gs.LABELS_FIVE), ["Channel", "Location", "Requirement", "Service", "VerificationMethod"])

    def test_concept_is_reported_separately_and_flagged_not_comparable(self):
        res = gs.score(self.docs, self.stale())
        c = res["concept"]
        self.assertEqual((c["tp"], c["fp"], c["fn"]), (0, 0, 1))
        self.assertIn("not comparable", c["note"])
        self.assertNotIn("Concept", res["per_label"])                  # kept out of the per-label content table

    def test_lenient_counts_template_only_predictions_as_correct(self):
        res = gs.score(self.docs, self.stale(), template_only=self.tmpl, lenient=True)
        otp = res["per_label"]["VerificationMethod"]
        self.assertEqual((otp["tp"], otp["fp"], otp["fn"]), (2, 0, 0))
        five = res["five_label"]
        self.assertEqual((five["precision"], five["recall"]), (1.0, 1.0))

    def test_lenient_is_not_applied_unless_asked_and_unpredicted_template_entries_change_nothing(self):
        strict = gs.score(self.docs, self.stale(), template_only=self.tmpl, lenient=False)
        self.assertEqual(strict["per_label"]["VerificationMethod"]["fp"], 2)
        lenient = gs.score(self.docs, self.stale(), template_only=self.tmpl, lenient=True)
        self.assertNotIn("Never Predicted", json.dumps(lenient["per_label"]))
        self.assertEqual(lenient["per_label"]["Channel"]["tp"], 1)

    def test_stale_versus_current_differ_when_the_extractor_gained_predictions(self):
        current = dict(self.stale())
        current["D1"] = self.stale()["D1"] + ["Concept:Billing & Invoices"]      # the overlay now finds the main-topic concept
        stale = gs.score(self.docs, self.stale())
        now = gs.score(self.docs, current)
        self.assertEqual(stale["concept"]["tp"], 0)
        self.assertEqual((now["concept"]["tp"], now["concept"]["fn"]), (1, 0))
        self.assertEqual(stale["five_label"], now["five_label"])               # the five content labels did not move

    def test_current_extractor_removing_a_prediction_changes_the_strict_score(self):
        current = dict(self.stale())
        current["D3"] = []
        res = gs.score(self.docs, current)
        self.assertEqual(res["per_label"]["VerificationMethod"]["fp"], 1)

    def test_disagreements_carry_kind_label_and_concept(self):
        res = gs.score(self.docs, self.stale())
        kinds = sorted((x["doc_id"], x["kind"], x["concept"]) for x in res["disagreements"])
        self.assertIn(("D1", "false_positive", "VerificationMethod:OTP"), kinds)
        self.assertIn(("D1", "false_negative", "Concept:Billing & Invoices"), kinds)
        self.assertIn(("D3", "false_positive", "VerificationMethod:OTP"), kinds)


class TestRealFiles(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.docs = gs.read_reviewed(REVIEWED)
        cls.tmpl = gs.load_template_only(TEMPLATE)

    def test_the_reviewed_sheet_is_the_same_twenty_documents_as_the_blank_template(self):
        from knowledge_graph.gold_sheet import SHEET_PATH
        with SHEET_PATH.open(encoding="utf-8", newline="") as handle:
            blank = {r["doc_id"]: r for r in csv.DictReader(handle)}
        self.assertEqual(sorted(self.docs), sorted(blank))
        self.assertEqual(len(self.docs), 20)
        self.assertTrue(all(r["correct_concepts"] == "" and r["notes"] == "" for r in blank.values()))     # the template stays blank

    def test_every_template_only_entry_is_a_prediction_of_the_sheet(self):
        for doc, entries in self.tmpl.items():
            self.assertTrue(entries <= set(self.docs[doc]["predicted"]), doc)

    def test_current_predictions_use_the_same_twenty_documents(self):
        current = gs.current_predictions()
        self.assertEqual(sorted(current), sorted(self.docs))

    def test_the_ai_label_status_is_never_called_human(self):
        text = REVIEWED.read_text(encoding="utf-8")
        self.assertEqual(text.count("NOT human-reviewed"), 20)


class TestDisagreementCauses(unittest.TestCase):
    """Every disagreement of the CURRENT extractor on the AI-labelled sheet gets one cause, read from the reviewer's notes and the template-only list."""

    @classmethod
    def setUpClass(cls):
        cls.docs = gs.read_reviewed(REVIEWED)
        cls.tmpl = gs.load_template_only(TEMPLATE)
        cls.res = gs.score(cls.docs, gs.current_predictions())
        cls.rows = gs.classify_disagreements(cls.res["disagreements"], cls.tmpl)

    def test_every_disagreement_has_a_cause(self):
        self.assertEqual(len(self.rows), len(self.res["disagreements"]))
        self.assertTrue(all(r["cause"] in gs.CAUSES for r in self.rows))
        self.assertEqual([r for r in self.rows if r["cause"] == "unclassified"], [])

    def test_counts_per_cause_for_the_five_content_labels(self):
        five = [r for r in self.rows if r["concept"].split(":")[0] in gs.LABELS_FIVE]
        counts = {}
        for r in five:
            counts[r["cause"]] = counts.get(r["cause"], 0) + 1
        self.assertEqual(counts, {"template sentence": 19, "weak passing mention": 2, "metadata-header echo": 1,
                                  "wrong sense": 3, "vocabulary gap": 2})
        self.assertEqual(sum(counts.values()), 27)                       # 25 false positives + 2 false negatives

    def test_vocabulary_gap_is_the_bare_the_app_channel(self):
        gaps = sorted((r["doc_id"], r["concept"]) for r in self.rows if r["cause"] == "vocabulary gap")
        self.assertEqual(gaps, [("FAQ_C07_013", "Channel:My NovaTel App"), ("MAN_ESIM_001", "Channel:My NovaTel App")])

    def test_false_positives_in_the_template_list_are_template_unless_the_notes_say_otherwise(self):
        wrong = {(r["doc_id"], r["concept"]) for r in self.rows if r["cause"] == "wrong sense"}
        self.assertEqual(wrong, {("INC_C05_INC_2026_0171", "Service:Complaint Registration"), ("TRN_002", "Service:Complaint Registration"),
                                 ("MAN_APP_001", "Service:Mobile Number Update")})
        echo = {(r["doc_id"], r["concept"]) for r in self.rows if r["cause"] == "metadata-header echo"}
        self.assertEqual(echo, {("MAN_APP_001", "Channel:Self-Care Portal")})

    def test_concept_disagreements_are_kept_apart(self):
        concept = [r for r in self.rows if r["concept"].startswith("Concept:")]
        self.assertTrue(concept)
        self.assertTrue(all(r["cause"] == "Concept not comparable" for r in concept))
        self.assertEqual(len(concept), 14)                               # false negatives of the current extractor on the main-topic concepts


if __name__ == "__main__":
    unittest.main(verbosity=2)
