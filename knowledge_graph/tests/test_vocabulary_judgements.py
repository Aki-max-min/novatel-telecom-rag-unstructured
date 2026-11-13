"""
KG fixes 4 (tests first): the wrong-sense judgements table docs/E13_kg_fixes4_judgements.csv must describe the overlay exactly.
Every (concept, phrase, document) match of the ten kept concepts, before (KG fixes 3 state) and after (now), is listed with a judgement
(correct sense / wrong sense / unsure), the snippet and the action. After the pass no match judged wrong sense may remain; matches judged
unsure are left unchanged; the number of wrong-sense matches before and after is counted from this table.
"""

import csv
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import content_extractor as ce  # noqa: E402
from knowledge_graph import vocabulary_overlay as vo  # noqa: E402
from knowledge_graph.entity_extractor import load_documents  # noqa: E402

TABLE = REPO_ROOT / "docs" / "E13_kg_fixes4_judgements.csv"
COLUMNS = ["concept", "phrase", "doc_id", "judgement", "before", "after", "action", "snippet"]
VALID = {"correct sense", "wrong sense", "unsure"}


def active_matches():
    docs = load_documents()
    ov = vo.load_overlay()
    out = set()
    for concept, phrases in ov.triggers.items():
        for phrase in phrases:
            pattern = ce._compile(phrase)
            for d in docs:
                if (d["document_id"], concept) not in ov.excluded and pattern.search(ce.body_text(d)):
                    out.add((concept, phrase, d["document_id"]))
    return out


class TestJudgements(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with TABLE.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            cls.columns = reader.fieldnames
            cls.rows = list(reader)

    def test_columns_and_valid_judgements(self):
        self.assertEqual(self.columns, COLUMNS)
        for r in self.rows:
            self.assertIn(r["judgement"], VALID)
            self.assertIn(r["before"], ("yes", "no"))
            self.assertIn(r["after"], ("yes", "no"))
            self.assertTrue(r["snippet"])
        keys = [(r["concept"], r["phrase"], r["doc_id"]) for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_table_lists_exactly_the_matches_that_exist_now(self):
        listed = {(r["concept"], r["phrase"], r["doc_id"]) for r in self.rows if r["after"] == "yes"}
        self.assertEqual(listed, active_matches())

    def test_before_state_is_the_80_matches_of_the_ten_kept_concepts(self):
        self.assertEqual(sum(r["before"] == "yes" for r in self.rows), 80)
        self.assertEqual(len({r["concept"] for r in self.rows if r["before"] == "yes"}), 10)

    def test_wrong_sense_matches_before_and_after(self):
        before = [r for r in self.rows if r["judgement"] == "wrong sense" and r["before"] == "yes"]
        after = [r for r in self.rows if r["judgement"] == "wrong sense" and r["after"] == "yes"]
        self.assertEqual(len(before), 7)
        self.assertEqual(len(after), 0)

    def test_unsure_matches_are_left_unchanged(self):
        for r in self.rows:
            if r["judgement"] == "unsure":
                self.assertEqual((r["before"], r["after"]), ("yes", "yes"), r)

    def test_every_change_has_an_action(self):
        for r in self.rows:
            if r["before"] == "yes" and r["after"] == "no":
                self.assertIn(r["action"], ("phrase narrowed", "phrase removed", "pair excluded", "concept dropped by rule (b)"), r)
            if r["before"] == "no" and r["after"] == "yes":
                self.assertEqual(r["action"], "replacement phrase", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
