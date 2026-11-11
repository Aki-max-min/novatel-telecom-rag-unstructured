"""
KG fixes 2, step 1 (tests first): the human gold sheet for the content extraction.
We prepare it; a human fills `correct_concepts`. Nothing here may fill a human column or use model output as gold.
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import gold_sheet  # noqa: E402
from knowledge_graph.entity_extractor import load_documents  # noqa: E402

COLUMNS = ["doc_id", "doc_type", "category", "text", "predicted_concepts", "evidence_phrase_in_text", "correct_concepts", "notes"]


class TestSelection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.docs = load_documents()
        cls.ids = gold_sheet.select_documents(cls.docs)
        cls.by_id = {d["document_id"]: d for d in cls.docs}

    def test_twenty_unique_documents(self):
        self.assertEqual(len(self.ids), 20)
        self.assertEqual(len(set(self.ids)), 20)

    def test_the_three_categories_without_concepts_each_get_one(self):
        cats = [self.by_id[i]["category"] for i in self.ids]
        for c in ("C11", "C12", "C24"):
            self.assertGreaterEqual(cats.count(c), 1, c)

    def test_stratified_by_the_seven_types_with_the_declared_quotas(self):
        types = [self.by_id[i]["document_id"].split("_")[0] for i in self.ids]
        for t, quota in gold_sheet.TYPE_QUOTAS.items():
            self.assertEqual(types.count(t), quota, t)
        self.assertEqual(sum(gold_sheet.TYPE_QUOTAS.values()), 20)

    def test_selection_is_deterministic_and_seed_dependent(self):
        self.assertEqual(self.ids, gold_sheet.select_documents(self.docs))
        self.assertNotEqual(self.ids, gold_sheet.select_documents(self.docs, seed=1))
        self.assertEqual(gold_sheet.SEED, 20260611)


class TestRows(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.docs = load_documents()
        cls.rows = gold_sheet.build_rows(cls.docs)

    def test_columns_and_human_columns_empty(self):
        self.assertEqual(gold_sheet.COLUMNS, COLUMNS)
        self.assertEqual(len(self.rows), 20)
        for r in self.rows:
            self.assertEqual(list(r.keys()), COLUMNS)
            self.assertEqual(r["correct_concepts"], "")
            self.assertEqual(r["notes"], "")

    def test_text_is_the_first_600_characters(self):
        by_id = {d["document_id"]: d for d in self.docs}
        for r in self.rows:
            self.assertLessEqual(len(r["text"]), 600)
            self.assertTrue(by_id[r["doc_id"]]["content"].startswith(r["text"][:50].rstrip()) or r["text"][:50] in by_id[r["doc_id"]]["content"])

    def test_every_prediction_has_an_evidence_phrase_that_is_in_the_text(self):
        by_id = {d["document_id"]: d for d in self.docs}
        for r in self.rows:
            preds = [p for p in r["predicted_concepts"].split("; ") if p]
            phrases = [p for p in r["evidence_phrase_in_text"].split(" | ") if p]
            self.assertEqual(len(preds), len(phrases), r["doc_id"])
            full = ((by_id[r["doc_id"]].get("title") or "") + "\n" + (by_id[r["doc_id"]].get("content") or "")).lower()
            for pred, ph in zip(preds, phrases):
                label_name, phrase = ph.split("=", 1)
                self.assertEqual(label_name, pred)
                self.assertIn(phrase.lower(), full)
                self.assertIn(":", pred)                       # label:name


class TestEvidenceProxy(unittest.TestCase):

    def test_pass_rate_on_the_corpus_and_it_can_fail(self):
        res = gold_sheet.evidence_check(load_documents())
        self.assertGreater(res["predictions"], 300)
        self.assertEqual(res["passed"] + len(res["failures"]), res["predictions"])
        self.assertEqual(res["label"], "precision PROXY, not validation")

    def test_a_missing_phrase_is_a_failure(self):
        doc = {"document_id": "X", "title": "t", "content": "nothing relevant here"}
        rec = [{"concept": "Refund", "concept_type": "Service", "document_id": "X", "matched_terms": ["refund"], "evidence_span": "refund"}]
        res = gold_sheet.evidence_check([doc], records=rec)
        self.assertEqual((res["predictions"], res["passed"]), (1, 0))


class TestScoring(unittest.TestCase):

    def write_sheet(self, d, rows):
        p = Path(d) / "filled.csv"
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        return p

    def row(self, doc, pred, correct):
        return {"doc_id": doc, "doc_type": "FAQ", "category": "C01", "text": "", "predicted_concepts": pred,
                "evidence_phrase_in_text": "", "correct_concepts": correct, "notes": ""}

    def test_tiny_fake_filled_sheet(self):
        rows = [self.row("D1", "Service:Refund; Channel:IVR", "Service:Refund; Channel:WhatsApp"),   # IVR wrong, WhatsApp missed
                self.row("D2", "Service:Recharge", "Service:Recharge"),                               # perfect
                self.row("D3", "", "NONE"),                                                           # correctly nothing
                self.row("D4", "Service:Refund", ""),                                                 # unreviewed: skipped
                ]
        with tempfile.TemporaryDirectory() as d:
            res = gold_sheet.score_sheet(self.write_sheet(d, rows))
        self.assertEqual(res["reviewed_rows"], 3)
        self.assertEqual(res["unreviewed_rows"], 1)
        svc = res["per_label"]["Service"]
        self.assertEqual((svc["tp"], svc["fp"], svc["fn"]), (2, 0, 0))
        self.assertEqual((svc["precision"], svc["recall"]), (1.0, 1.0))
        ch = res["per_label"]["Channel"]
        self.assertEqual((ch["tp"], ch["fp"], ch["fn"]), (0, 1, 1))
        self.assertEqual((ch["precision"], ch["recall"]), (0.0, 0.0))
        kinds = sorted((x["doc_id"], x["kind"], x["concept"]) for x in res["disagreements"])
        self.assertEqual(kinds, [("D1", "false_negative", "Channel:WhatsApp"), ("D1", "false_positive", "Channel:IVR")])

    def test_an_unfilled_sheet_prints_no_scores(self):
        rows = [self.row("D1", "Service:Refund", "")]
        with tempfile.TemporaryDirectory() as d:
            res = gold_sheet.score_sheet(self.write_sheet(d, rows))
        self.assertEqual(res["reviewed_rows"], 0)
        self.assertEqual(res["per_label"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
