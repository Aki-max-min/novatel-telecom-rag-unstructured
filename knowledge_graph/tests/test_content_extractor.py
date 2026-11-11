"""
KG fixes 2, step 2 (tests first). The content extractor had no tests: the first block pins the CURRENT behaviour (boundary-safe matching,
negation exclusion, evidence recording, determinism); the second block specifies the new concept-name mention rule on the document BODY
(metadata header lines and the trailing "Topic:" footer are template echoes of the category name and must not count).
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph import content_extractor as ce  # noqa: E402
from knowledge_graph.entity_extractor import load_documents  # noqa: E402


def doc(text, document_id="FAQ_X_001", title="t", category="C99"):
    return {"document_id": document_id, "title": title, "content": text, "category": category}


def concepts(document):
    return {(r["concept_type"], r["concept"]) for r in ce.extract_document_concepts(document)}


class TestExistingBehaviour(unittest.TestCase):

    def test_port_does_not_fire_inside_portal(self):
        self.assertNotIn(("Service", "Number Portability"), concepts(doc("Use the portal to log in.")))
        self.assertIn(("Service", "Number Portability"), concepts(doc("You can port number to us.")))

    def test_pan_does_not_fire_inside_pan_india(self):
        self.assertEqual(concepts(doc("Pan-India outage reported.")) & {("Requirement", "PAN"), ("VerificationMethod", "PAN")}, set())

    def test_negated_escalation_and_heading_only_escalation_are_excluded(self):
        self.assertNotIn(("Service", "Complaint Registration"), concepts(doc("This is a service request rather than a general support escalation.")))
        self.assertNotIn(("Service", "Complaint Registration"), concepts(doc("text\n### Escalation\nmore text")))
        self.assertIn(("Service", "Complaint Registration"), concepts(doc("Please raise a complaint with care.")))

    def test_every_record_carries_trigger_evidence_and_field(self):
        recs = ce.extract_document_concepts(doc("Please recharge your account via UPI mandate."))
        by = {r["concept"]: r for r in recs}
        self.assertIn("Recharge", by)
        self.assertIn("recharge", by["Recharge"]["matched_terms"])
        self.assertIn("recharge", by["Recharge"]["evidence"].lower())
        self.assertEqual(by["Recharge"]["evidence_field"], "content")

    def test_extraction_is_deterministic(self):
        docs = load_documents()
        a, b = ce.extract_content(docs), ce.extract_content(docs)
        self.assertEqual(a["edges"], b["edges"])
        self.assertEqual(a["stats"], b["stats"])

    def test_baseline_counts_on_the_corpus(self):
        stats = ce.extract_content(load_documents())["stats"]
        self.assertEqual(stats["documents_read"], 148)
        self.assertEqual(stats["documents_with_at_least_one_content_edge"], 125)


class TestBodyText(unittest.TestCase):

    HEADER = ("# Title\n\n**Document ID:** INC_C04_X\n**Category:** C04 – Billing & Invoices\n**Department:** Billing\n"
              "**Customer Scope:** all\n**Last Updated:** 2026-06-15\n**Version:** 1.0\n**Source Authority:** Internal\n**Channel:** Email\n\n---\n")

    def test_metadata_header_lines_are_removed_but_other_bold_lines_stay(self):
        body = ce.body_text(doc(self.HEADER + "**Subject:** About your Billing & Invoices query\nText."))
        self.assertNotIn("Document ID", body)
        self.assertNotIn("**Category:**", body)
        self.assertNotIn("Source Authority", body)
        self.assertIn("**Channel:** Email", body)                    # not a category echo: kept
        self.assertIn("About your Billing & Invoices query", body)

    def test_trailing_topic_footer_is_removed(self):
        body = ce.body_text(doc("Question: q\n\nAnswer: a\n\nRelated documents referenced in metadata: KB_C08_overview.\n\nTopic: Network Coverage & Outages"))
        self.assertNotIn("Topic:", body)
        self.assertNotIn("Network Coverage & Outages", body)
        self.assertIn("Answer: a", body)

    def test_a_topic_word_inside_the_text_is_not_a_footer(self):
        body = ce.body_text(doc("Topic: sentence in the middle\nmore text after it"))
        self.assertIn("Topic: sentence in the middle", body)

    def test_title_is_part_of_the_body(self):
        self.assertIn("My Title", ce.body_text(doc("x", title="My Title")))


class TestConceptNameMentions(unittest.TestCase):

    def test_families_default_is_a_tuple_of_vocabulary_names(self):
        from knowledge_graph.concept_bridge import concept_vocabulary, load_crosswalk
        self.assertIsInstance(ce.CONCEPT_NAME_FAMILIES, tuple)
        self.assertTrue(set(ce.CONCEPT_NAME_FAMILIES) <= set(concept_vocabulary(load_crosswalk())))

    def test_body_mention_is_found_with_evidence(self):
        d = doc("Question: Is it covered?\n\nAnswer: Check Device Compatibility under Help.")
        recs = ce.extract_concept_mentions(d, families=("Device Compatibility",))
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual((r["concept"], r["concept_type"], r["document_id"]), ("Device Compatibility", "Concept", "FAQ_X_001"))
        self.assertEqual(r["evidence_span"].lower(), "device compatibility")
        self.assertIn("device compatibility", r["evidence"].lower())

    def test_the_category_echo_in_header_and_footer_is_not_a_mention(self):
        d = doc("**Document ID:** X\n**Category:** C12 – Device Compatibility\n\nPlain text.\n\nTopic: Device Compatibility")
        self.assertEqual(ce.extract_concept_mentions(d, families=("Device Compatibility",)), [])

    def test_boundary_safe(self):
        self.assertEqual(ce.extract_concept_mentions(doc("Pre-device compatibilityx"), families=("Device Compatibility",)), [])

    def test_unknown_family_name_is_rejected(self):
        with self.assertRaises(ValueError):
            ce.extract_concept_mentions(doc("x"), families=("Not A Concept",))

    def test_extract_content_emits_mentions_concept_edges_only_for_active_families(self):
        d = doc("Answer: Check Device Compatibility.")
        none = ce.extract_content([d], families=())
        self.assertEqual(none["concept_mention_edges"], [])
        some = ce.extract_content([d], families=("Device Compatibility",))
        edges = some["concept_mention_edges"]
        self.assertEqual(len(edges), 1)
        e = edges[0]
        self.assertEqual((e["source"], e["target"], e["type"]), ("Document::FAQ_X_001", "Concept::Device Compatibility", "MENTIONS_CONCEPT"))
        self.assertEqual(e["properties"]["confidence"], "pattern_match")
        self.assertTrue(e["properties"]["evidence_span"])
        self.assertEqual(e["properties"]["rule"], "concept_name_in_body")
        self.assertEqual(some["stats"]["documents_with_any_content_concept"], 1)
        self.assertEqual(none["stats"]["documents_with_any_content_concept"], 0)

    def test_existing_edges_and_baseline_count_do_not_move_with_families(self):
        docs = load_documents()
        base = ce.extract_content(docs, families=())
        full = ce.extract_content(docs, families=tuple(ce.CONCEPT_NAME_FAMILIES) or ("Network Coverage",))
        self.assertEqual(base["edges"], full["edges"])
        self.assertEqual(base["stats"]["documents_with_at_least_one_content_edge"], 125)

    def test_every_new_edge_passes_the_evidence_check(self):
        from knowledge_graph.gold_sheet import evidence_check  # noqa: F401  (same proxy, applied to mentions below)
        docs = load_documents()
        res = ce.extract_content(docs, families=("Network Coverage", "Device Compatibility", "Roaming"))
        by_id = {d["document_id"]: d for d in docs}
        self.assertTrue(res["concept_mention_edges"])
        for e in res["concept_mention_edges"]:
            did = e["source"].split("::", 1)[1]
            self.assertIn(e["properties"]["evidence_span"].lower(), ce.body_text(by_id[did]).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
