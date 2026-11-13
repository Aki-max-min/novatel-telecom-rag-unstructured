"""
KG fixes 3, step 1 (tests first): the Gap 5 vocabulary proposal as an OVERLAY file (knowledge_graph/vocabulary_extension.json) and its loader.
The shared ontology (ontology/, 23 concepts in the crosswalk) is never edited; new concepts live only in the overlay.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import vocabulary_overlay as vo  # noqa: E402
from knowledge_graph.concept_bridge import concept_vocabulary, load_crosswalk  # noqa: E402

PROPOSAL = {   # gap5_vocabulary_extension_proposal.json, concept -> (status, trigger phrases)
    "Device Compatibility": ("EXTEND existing", ["VoLTE", "HD Voice", "IMEI"]),
    "Billing & Invoices": ("EXTEND existing", ["billed twice", "duplicate charges", "billing batch job", "final bill"]),
    "Network Outages": ("EXTEND existing", ["cell cluster", "backhaul"]),
    "Security & Fraud": ("EXTEND existing", ["phishing", "anti-fraud"]),
    "SIM Card Services": ("EXTEND existing", ["not provisioned", "re-provisioned"]),
    "Enterprise & Business Services": ("EXTEND existing", ["Enterprise Business Connectivity", "MPLS", "leased-line", "Enterprise IoT"]),
    "IoT & M2M Services": ("NEW", ["IoT", "M2M", "NB-IoT", "LTE-M"]),
    "Privacy & Data Protection": ("NEW", ["Privacy Policy", "Privacy Settings", "personal data", "data-deletion"]),
    "International Calling & ISD": ("NEW", ["ISD", "International Long Distance", "international calls"]),
    "Account Closure & Deactivation": ("NEW", ["Account Closure", "close my postpaid connection", "Close Connection", "closure request",
                                                "deactivate", "deactivated", "cooling-off", "Reactivation"]),
    "Fair Usage Policy (FUP)": ("NEW", ["FUP", "Fair Usage Policy", "high-speed data limit"]),
    "Connectivity Troubleshooting": ("NEW", ["Reset Network Settings", "Airplane Mode"]),
    "Accessibility & Communication Preferences": ("NEW", ["Communication Preferences", "Accessibility Services", "large-print"]),
}


def write(d, payload):
    p = Path(d) / "overlay.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def minimal(**over):
    base = {"status": "proposed, pending ontology-owner approval", "generic_template_words": ["outage", "bill", "troubleshooting"],
            "concepts": [{"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE"]},
                         {"concept": "Brand New Thing", "status": "NEW", "trigger_phrases": ["gizmo"]}],
            "exclusions": [], "dropped": {}, "dropped_phrases": {}}
    base.update(over)
    return base


class TestOverlayFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.overlay = vo.load_overlay()

    def test_the_file_exists_and_is_marked_as_proposed(self):
        self.assertTrue(vo.OVERLAY_PATH.exists())
        self.assertEqual(self.overlay.status, "proposed, pending ontology-owner approval")

    def test_content_is_the_proposal(self):
        got = {c["concept"]: (c["status"], c["trigger_phrases"]) for c in self.overlay.raw["concepts"]}
        # KG fixes 4 appended three specific phrases to Account Closure & Deactivation (replacing the bare deactivate/deactivated, which are kept in the file as narrowed)
        expected = dict(PROPOSAL)
        status, phrases = expected["Account Closure & Deactivation"]
        expected["Account Closure & Deactivation"] = (status, phrases + ["permanently deactivate", "deactivated for non-payment", "Deactivated Connection"])
        self.assertEqual(got, expected)
        self.assertEqual([c["concept"] for c in self.overlay.raw["concepts"]], list(PROPOSAL))     # proposal order
        self.assertEqual(sum(s == "EXTEND existing" for s, _ in PROPOSAL.values()), 6)
        self.assertEqual(sum(s == "NEW" for s, _ in PROPOSAL.values()), 7)

    def test_new_concepts_are_not_in_the_shared_vocabulary_and_extended_ones_are(self):
        shared = set(concept_vocabulary(load_crosswalk()))
        self.assertEqual(len(shared), 23)
        for name, (status, _) in PROPOSAL.items():
            self.assertEqual(name in shared, status == "EXTEND existing", name)

    def test_the_shared_ontology_was_not_touched(self):
        # some NEW names equal DOCUMENT CATEGORY names in the catalogue (that is fine); none may be a shared-concept name in the crosswalk
        onto = json.loads((REPO_ROOT / "ontology" / "ontology_schema.json").read_text(encoding="utf-8"))
        shared = {r["shared_domain_concept"] for r in onto["structured_document_crosswalk"]["rows"]}
        self.assertEqual(len(shared), 23)
        for name, (status, _) in PROPOSAL.items():
            if status == "NEW":
                self.assertNotIn(name, shared)

    def test_the_two_doubtful_edges_are_in_the_documented_exclusion_list(self):
        pairs = {(e["document_id"], e["concept"]) for e in self.overlay.raw["exclusions"]}
        self.assertEqual(pairs, {("FAQ_C11_022", "Network Coverage"), ("FAQ_C09_017", "Device Compatibility")})
        self.assertTrue(all(e["reason"] for e in self.overlay.raw["exclusions"]))
        self.assertEqual(self.overlay.excluded, pairs)

    def test_no_phrase_is_a_generic_template_word(self):
        generic = {w.lower() for w in self.overlay.generic_words}
        self.assertTrue({"outage", "troubleshooting", "bill"} <= generic)
        for c in self.overlay.raw["concepts"]:
            for p in c["trigger_phrases"]:
                self.assertNotIn(p.lower(), generic)


class TestLoader(unittest.TestCase):

    def load(self, payload):
        with tempfile.TemporaryDirectory() as d:
            return vo.load_overlay(write(d, payload))

    def test_missing_file_is_an_empty_overlay(self):
        ov = vo.load_overlay(Path("/nonexistent/overlay.json"))
        self.assertEqual(ov.triggers, {})
        self.assertEqual(ov.new_concepts, [])
        self.assertEqual(ov.excluded, set())

    def test_triggers_and_new_concepts(self):
        ov = self.load(minimal())
        self.assertEqual(ov.triggers, {"Device Compatibility": ["VoLTE"], "Brand New Thing": ["gizmo"]})
        self.assertEqual(ov.new_concepts, ["Brand New Thing"])

    def test_extend_must_name_a_shared_concept(self):
        with self.assertRaises(ValueError):
            self.load(minimal(concepts=[{"concept": "Not Shared", "status": "EXTEND existing", "trigger_phrases": ["x1"]}]))

    def test_new_must_not_shadow_a_shared_concept(self):
        with self.assertRaises(ValueError):
            self.load(minimal(concepts=[{"concept": "Roaming", "status": "NEW", "trigger_phrases": ["x1"]}]))

    def test_generic_template_words_are_refused(self):
        for word in ("outage", "Bill", "troubleshooting"):
            with self.assertRaises(ValueError, msg=word):
                self.load(minimal(concepts=[{"concept": "Network Outages", "status": "EXTEND existing", "trigger_phrases": [word]}]))

    def test_unknown_status_and_duplicate_concepts_are_refused(self):
        with self.assertRaises(ValueError):
            self.load(minimal(concepts=[{"concept": "Roaming", "status": "MAYBE", "trigger_phrases": ["x1"]}]))
        dup = {"concept": "Roaming", "status": "EXTEND existing", "trigger_phrases": ["x1"]}
        with self.assertRaises(ValueError):
            self.load(minimal(concepts=[dup, dup]))

    def test_exclusion_must_name_a_known_concept(self):
        with self.assertRaises(ValueError):
            self.load(minimal(exclusions=[{"document_id": "D1", "concept": "Nope", "reason": "r"}]))
        ov = self.load(minimal(exclusions=[{"document_id": "D1", "concept": "Network Coverage", "reason": "r"}]))
        self.assertEqual(ov.excluded, {("D1", "Network Coverage")})

    def test_dropped_concepts_and_phrases_stay_in_the_file_but_leave_the_triggers(self):
        ov = self.load(minimal(dropped={"Brand New Thing": "fails (b)"},
                               concepts=[{"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE", "IMEI"]},
                                         {"concept": "Brand New Thing", "status": "NEW", "trigger_phrases": ["gizmo"]}],
                               dropped_phrases={"Device Compatibility": {"IMEI": "hub phrase"}}))
        self.assertEqual(ov.triggers, {"Device Compatibility": ["VoLTE"]})
        self.assertEqual(ov.new_concepts, [])
        self.assertEqual(len(ov.raw["concepts"]), 2)                     # nothing deleted


class TestNarrowedPhrases(unittest.TestCase):
    """KG fixes 4: a phrase narrowed for a documented wrong sense stays in the file (`narrowed_phrases`) but is no longer a trigger."""

    CONCEPT = {"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE", "IMEI", "VoLTE profile"]}

    def load(self, payload):
        with tempfile.TemporaryDirectory() as d:
            return vo.load_overlay(write(d, payload))

    def test_narrowed_phrase_is_inactive_but_kept_in_the_file(self):
        ov = self.load(minimal(concepts=[self.CONCEPT], narrowed_phrases={"Device Compatibility": {"IMEI": {"reason": "wrong sense", "documents": ["D1"]}}}))
        self.assertEqual(ov.triggers, {"Device Compatibility": ["VoLTE", "VoLTE profile"]})
        self.assertIn("IMEI", ov.raw["concepts"][0]["trigger_phrases"])
        self.assertEqual(ov.narrowed, {"Device Compatibility": ["IMEI"]})

    def test_a_narrowed_phrase_must_exist_in_the_concept_and_carry_a_reason(self):
        with self.assertRaises(ValueError):
            self.load(minimal(concepts=[self.CONCEPT], narrowed_phrases={"Device Compatibility": {"Nope": {"reason": "r", "documents": []}}}))
        with self.assertRaises(ValueError):
            self.load(minimal(concepts=[self.CONCEPT], narrowed_phrases={"Device Compatibility": {"IMEI": {"documents": []}}}))

    def test_the_real_overlay_records_the_requested_narrowing(self):
        ov = vo.load_overlay()
        self.assertEqual(sorted(ov.narrowed["Account Closure & Deactivation"]), ["deactivate", "deactivated"])
        self.assertEqual(ov.narrowed["Connectivity Troubleshooting"], ["Airplane Mode"])
        active = ov.triggers["Account Closure & Deactivation"]
        for phrase in ("permanently deactivate", "deactivated for non-payment", "Deactivated Connection"):
            self.assertIn(phrase, active)
        for phrase in ("deactivate", "deactivated"):
            self.assertNotIn(phrase, active)
        for entries in ov.raw["narrowed_phrases"].values():
            for info in entries.values():
                self.assertTrue(info["reason"])
                self.assertTrue(info["documents"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
