"""
KG fixes 3, step 4/5 (tests first): the acceptance checks of the pre-declared rule (docs/E13_kg_fixes3.md) on a tiny synthetic corpus.
  phrase hub rule : a single phrase matching more than 10% of the documents is dropped (14 of 148 in the real run)
  (a) concept <= 10% of documents; an EXISTING concept grows by <= 2 documents over its existing group
  (b) a NEW concept links at least 2 documents
  (c) 100% of the new edges have their evidence phrase in the body (proxy, not validation)
  decisions are recorded in the overlay (dropped / dropped_phrases); nothing is deleted from the rule list.
"""

import copy
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import evaluate_vocabulary_extension as ev  # noqa: E402
from knowledge_graph import vocabulary_overlay as vo  # noqa: E402


def d(i, text):
    return {"document_id": i, "title": "t", "content": text, "category": "C99"}


def raw(concepts, exclusions=()):
    return {"status": "proposed, pending ontology-owner approval", "generic_template_words": ["outage"],
            "concepts": concepts, "exclusions": list(exclusions), "dropped": {}, "dropped_phrases": {}}


DEV = {"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE"]}
IOT = {"concept": "IoT & M2M Services", "status": "NEW", "trigger_phrases": ["IoT"]}
CORPUS = [d(f"D{i:02d}", "filler text") for i in range(20)]            # 20 documents: 10% = 2


def corpus_with(**texts):
    docs = [dict(x) for x in CORPUS]
    for doc in docs:
        if doc["document_id"] in texts:
            doc["content"] = texts[doc["document_id"]]
    return docs


class TestOverlayFromRaw(unittest.TestCase):

    def test_overlay_from_raw_equals_load_overlay_semantics(self):
        ov = vo.overlay_from_raw(raw([DEV, IOT]))
        self.assertEqual(ov.triggers, {"Device Compatibility": ["VoLTE"], "IoT & M2M Services": ["IoT"]})
        self.assertEqual(ov.new_concepts, ["IoT & M2M Services"])


class TestAcceptance(unittest.TestCase):

    def run_eval(self, docs, concepts, groups=None, baseline=(), exclusions=()):
        return ev.evaluate(docs, raw(concepts, exclusions), groups or {}, set(baseline))

    def row(self, res, concept):
        return next(r for r in res["rows"] if r["concept"] == concept)

    def test_a_concept_inside_the_limits_is_kept_and_counts_newly_covered(self):
        docs = corpus_with(D01="VoLTE fails.", D02="Enable VoLTE.")
        res = self.run_eval(docs, [DEV], groups={"Device Compatibility": {"D01", "D02"}}, baseline={"D02"})
        r = self.row(res, "Device Compatibility")
        self.assertEqual((r["decision"], r["docs"], r["growth"], r["newly_covered"]), ("KEEP", 2, 0, 1))
        self.assertEqual(r["evidence"], "2/2")
        self.assertEqual(res["coverage_after"], 2)

    def test_phrase_hub_rule_drops_the_phrase_not_the_concept(self):
        docs = corpus_with(D00="VoLTE", D01="VoLTE", D02="VoLTE", D03="IMEI check")           # VoLTE matches 3 > 2
        dev = {"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE", "IMEI"]}
        res = self.run_eval(docs, [dev])
        self.assertIn("VoLTE", res["dropped_phrases"]["Device Compatibility"])
        self.assertNotIn("IMEI", res["dropped_phrases"].get("Device Compatibility", {}))
        r = self.row(res, "Device Compatibility")
        self.assertEqual(r["matched"], ["D03"])
        self.assertEqual(r["decision"], "KEEP")

    def test_extend_growth_above_two_drops_the_concept(self):
        dev = {"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE", "IMEI"]}
        docs = corpus_with(D01="VoLTE", D02="IMEI", D03="IMEI x")
        res = self.run_eval(docs, [dev], groups={"Device Compatibility": set()})
        r = self.row(res, "Device Compatibility")
        self.assertEqual(r["growth"], 3)
        self.assertEqual(r["decision"], "DROP")
        self.assertIn("Device Compatibility", res["dropped"])
        self.assertTrue(any("growth" in why for why in r["reasons"]))

    def test_growth_of_exactly_two_is_allowed(self):
        docs = corpus_with(D01="VoLTE", D02="VoLTE")
        res = self.run_eval(docs, [DEV], groups={"Device Compatibility": set()})
        self.assertEqual(self.row(res, "Device Compatibility")["decision"], "KEEP")

    def test_a_new_concept_with_one_document_is_dropped(self):
        res = self.run_eval(corpus_with(D01="IoT meters"), [IOT])
        r = self.row(res, "IoT & M2M Services")
        self.assertEqual((r["decision"], r["docs"]), ("DROP", 1))
        self.assertTrue(any("at least 2" in why for why in r["reasons"]))

    def test_a_new_concept_with_two_documents_is_kept_and_growth_equals_documents(self):
        res = self.run_eval(corpus_with(D01="IoT meters", D02="IoT SIMs"), [IOT])
        r = self.row(res, "IoT & M2M Services")
        self.assertEqual((r["decision"], r["growth"]), ("KEEP", 2))               # a NEW concept has no existing group; the growth rule is for existing ones

    def test_a_concept_matching_more_than_ten_percent_is_dropped(self):
        docs = corpus_with(D01="IoT", D02="IoT", D03="IoT")                          # 3 > 2 (the phrase itself is a hub: dropped), concept then has no documents
        res = self.run_eval(docs, [IOT])
        self.assertIn("IoT", res["dropped_phrases"]["IoT & M2M Services"])
        self.assertEqual(self.row(res, "IoT & M2M Services")["decision"], "DROP")

    def test_exclusions_apply_before_counting(self):
        docs = corpus_with(D01="IoT a", D02="IoT b")
        ex = [{"document_id": "D02", "concept": "IoT & M2M Services", "reason": "r"}]
        res = self.run_eval(docs, [IOT], exclusions=ex)
        self.assertEqual(self.row(res, "IoT & M2M Services")["decision"], "DROP")     # only one document left

    def test_header_footer_and_related_sections_never_count(self):
        docs = corpus_with(D01="**Category:** x IoT\n\nTopic: IoT", D02="## Related Information\n\nIoT")
        res = self.run_eval(docs, [IOT])
        self.assertEqual(self.row(res, "IoT & M2M Services")["docs"], 0)

    def test_decisions_are_recorded_without_deleting_rules(self):
        base = raw([DEV, IOT])
        res = ev.evaluate(corpus_with(D01="IoT"), base, {}, set())
        applied = ev.apply_decisions(base, res)
        self.assertEqual([c["concept"] for c in applied["concepts"]], ["Device Compatibility", "IoT & M2M Services"])
        self.assertEqual(applied["concepts"], base["concepts"])
        self.assertIn("IoT & M2M Services", applied["dropped"])                       # one document: fails (b)
        self.assertNotIn("Device Compatibility", applied["dropped"])                  # an EXTEND concept with no match fails no rule; it just creates no edge
        ov = vo.overlay_from_raw(applied)
        self.assertEqual(ov.triggers, {"Device Compatibility": ["VoLTE"]})

    def test_evaluation_is_independent_of_concept_order(self):
        docs = corpus_with(D01="VoLTE and IoT", D02="IoT")
        a = ev.evaluate(docs, raw([DEV, IOT]), {}, set())
        b = ev.evaluate(docs, raw([IOT, DEV]), {}, set())
        self.assertEqual({r["concept"]: r["decision"] for r in a["rows"]}, {r["concept"]: r["decision"] for r in b["rows"]})

    def test_uncovered_documents_are_listed(self):
        docs = corpus_with(D01="VoLTE")
        res = self.run_eval(docs, [DEV], baseline={"D05"})
        self.assertNotIn("D01", res["uncovered"])
        self.assertIn("D02", res["uncovered"])
        self.assertEqual(res["coverage_after"], 2)                                    # the baseline document D05 plus D01

    def test_unexpected_matches_are_reported_with_a_snippet(self):
        docs = corpus_with(D01="VoLTE fails", D02="VoLTE elsewhere")
        res = ev.unexpected_matches(docs, vo.overlay_from_raw(raw([DEV])), {("Device Compatibility", "VoLTE", "D01")})
        self.assertEqual([(u["concept"], u["phrase"], u["doc_id"]) for u in res["unexpected"]], [("Device Compatibility", "VoLTE", "D02")])
        self.assertIn("VoLTE", res["unexpected"][0]["snippet"])
        self.assertEqual(res["missing"], [])
        res2 = ev.unexpected_matches(docs, vo.overlay_from_raw(raw([DEV])), {("Device Compatibility", "VoLTE", "D09")})
        self.assertEqual(res2["missing"], [("Device Compatibility", "VoLTE", "D09")])


class TestNarrowedPhrasesSurviveTheAcceptanceRun(unittest.TestCase):

    def test_narrowed_phrases_are_not_matched_and_apply_keeps_them(self):
        base = raw([{"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE", "IMEI"]}])
        base["narrowed_phrases"] = {"Device Compatibility": {"IMEI": {"reason": "wrong sense", "documents": ["D02"]}}}
        docs = corpus_with(D01="VoLTE here", D02="check IMEI")
        res = ev.evaluate(docs, base, {}, set())
        self.assertEqual(next(r for r in res["rows"] if r["concept"] == "Device Compatibility")["matched"], ["D01"])
        applied = ev.apply_decisions(base, res)
        self.assertEqual(applied["narrowed_phrases"], base["narrowed_phrases"])
        self.assertNotIn("IMEI", applied["dropped_phrases"].get("Device Compatibility", {}))


class TestRealCorpus(unittest.TestCase):
    """The accepted outcome of the real run (docs/E13_kg_fixes3.md) and the consistency of the decisions recorded in the overlay file."""

    @classmethod
    def setUpClass(cls):
        import json
        from unittest import mock
        from knowledge_graph import content_extractor as ce
        from knowledge_graph.entity_extractor import extract_entities, load_documents
        from knowledge_graph.evaluate_concept_families import concept_groups
        cls.docs = load_documents()
        with mock.patch.object(ce, "OVERLAY_ENABLED", False):
            before = ce.extract_content(cls.docs)
        covered = {k for k, v in before["per_document"].items() if v} | {m["document_id"] for m in before["concept_mentions"]}
        five = {k for k, v in before["per_document"].items() if v}
        groups = concept_groups(cls.docs, before["per_document"], extract_entities(cls.docs)["nodes"] + before["nodes"])
        cls.raw = json.loads(vo.OVERLAY_PATH.read_text(encoding="utf-8"))
        cls.result = ev.evaluate(cls.docs, cls.raw, groups, covered, five)
        cls.baseline = len(covered)

    def test_coverage_rises_from_129_to_144_and_four_documents_stay_uncovered(self):
        self.assertEqual(self.baseline, 129)
        self.assertEqual(self.result["coverage_after"], 144)
        self.assertEqual(self.result["uncovered"], ["FAQ_C11_021", "FAQ_C11_022", "FAQ_C23_045", "INC_C04_INC_2026_0163"])

    def test_recorded_decisions_equal_a_fresh_evaluation(self):
        self.assertEqual(self.raw["dropped"], self.result["dropped"])
        self.assertEqual(self.raw["dropped_phrases"], self.result["dropped_phrases"])
        self.assertEqual(sorted(self.result["dropped"]), ["Billing & Invoices", "Enterprise & Business Services", "International Calling & ISD"])

    def test_no_kept_concept_breaks_the_limits(self):
        for r in self.result["rows"]:
            if r["decision"] == "KEEP":
                self.assertLessEqual(r["docs"], 14, r["concept"])
                self.assertEqual(r["evidence"], f"{r['docs']}/{r['docs']}")
                if r["status"] == "EXTEND existing":
                    self.assertLessEqual(r["growth"], 2, r["concept"])
                else:
                    self.assertGreaterEqual(r["docs"], 2, r["concept"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
