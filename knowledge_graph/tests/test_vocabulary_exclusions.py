"""
KG fixes 3, step 3 (tests first): an explicit, documented exclusion list in the overlay removes (document, concept) pairs whatever rule produced them -
the name-family rules and the overlay phrases stay in place (rules are not deleted). The two doubtful edges of KG fixes 2 are the entries:
FAQ_C11_022 -> Network Coverage and FAQ_C09_017 -> Device Compatibility.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import content_extractor as ce  # noqa: E402
from knowledge_graph import vocabulary_overlay as vo  # noqa: E402
from knowledge_graph.entity_extractor import load_documents  # noqa: E402


def overlay(exclusions, concepts=()):
    payload = {"status": "proposed, pending ontology-owner approval", "generic_template_words": [], "concepts": list(concepts),
               "exclusions": exclusions, "dropped": {}, "dropped_phrases": {}}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "o.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return vo.load_overlay(p)


def doc(text, document_id):
    return {"document_id": document_id, "title": "t", "content": text, "category": "C99"}


class TestExclusions(unittest.TestCase):

    def test_an_excluded_pair_is_not_extracted_from_the_name_family(self):
        ov = overlay([{"document_id": "D1", "concept": "Network Coverage", "reason": "r"}])
        self.assertEqual(ce.extract_concept_mentions(doc("Network Coverage matters.", "D1"), families=("Network Coverage",), overlay=ov), [])
        self.assertEqual(len(ce.extract_concept_mentions(doc("Network Coverage matters.", "D2"), families=("Network Coverage",), overlay=ov)), 1)

    def test_an_excluded_pair_is_not_extracted_from_overlay_phrases_either(self):
        ext = {"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE"]}
        ov = overlay([{"document_id": "D1", "concept": "Device Compatibility", "reason": "r"}], [ext])
        self.assertEqual(ce.extract_concept_mentions(doc("VoLTE here.", "D1"), families=(), overlay=ov), [])
        self.assertEqual(len(ce.extract_concept_mentions(doc("VoLTE here.", "D2"), families=(), overlay=ov)), 1)

    def test_exclusion_is_per_pair_not_per_document_or_concept(self):
        ov = overlay([{"document_id": "D1", "concept": "Network Coverage", "reason": "r"}])
        text = "Network Coverage and Device Compatibility."
        got = {r["concept"] for r in ce.extract_concept_mentions(doc(text, "D1"), families=("Network Coverage", "Device Compatibility"), overlay=ov)}
        self.assertEqual(got, {"Device Compatibility"})

    def test_the_two_doubtful_edges_are_gone_from_the_real_extraction_and_nothing_else_moved(self):
        with mock.patch.object(ce, "OVERLAY_ENABLED", False):
            before = ce.extract_content(load_documents())
        res = ce.extract_content(load_documents())
        pairs = lambda r: {(e["source"].split("::", 1)[1], e["target"].split("::", 1)[1]) for e in r["concept_mention_edges"]}  # noqa: E731
        self.assertIn(("FAQ_C11_022", "Network Coverage"), pairs(before))
        self.assertIn(("FAQ_C09_017", "Device Compatibility"), pairs(before))
        self.assertNotIn(("FAQ_C11_022", "Network Coverage"), pairs(res))
        self.assertNotIn(("FAQ_C09_017", "Device Compatibility"), pairs(res))
        old_pairs = pairs(before) - {("FAQ_C11_022", "Network Coverage"), ("FAQ_C09_017", "Device Compatibility")}
        self.assertTrue(old_pairs <= pairs(res))                          # every other earlier edge is still there
        self.assertEqual(before["edges"], res["edges"])                    # the original five-label extraction is untouched

    def test_the_name_family_rules_are_still_declared(self):
        self.assertEqual(ce.CONCEPT_NAME_FAMILIES, ("Device Compatibility", "Network Coverage"))
        self.assertEqual(vo.load_overlay().raw["exclusions"][0]["document_id"], "FAQ_C11_022")


if __name__ == "__main__":
    unittest.main(verbosity=2)
