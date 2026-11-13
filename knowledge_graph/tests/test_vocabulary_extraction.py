"""
KG fixes 3, step 2 (tests first): the extractor reads the vocabulary overlay. Boundary-safe, case-insensitive matching on the document BODY only
(metadata header, `Topic:` footer and the Related Information / Related Documents / References sections removed); MENTIONS_CONCEPT edges with
phrase, field and snippet; NEW concepts become Concept nodes with source="vocabulary_extension"; dropped concepts and phrases leave no trace in the graph.
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
from knowledge_graph.concept_nodes import build_concept_metadata  # noqa: E402
from knowledge_graph.entity_extractor import load_documents  # noqa: E402


def doc(text, document_id="FAQ_X_001", title="t"):
    return {"document_id": document_id, "title": title, "content": text, "category": "C99"}


def overlay(concepts, **extra):
    payload = {"status": "proposed, pending ontology-owner approval", "generic_template_words": ["outage", "troubleshooting", "bill"],
               "concepts": concepts, "exclusions": [], "dropped": {}, "dropped_phrases": {}}
    payload.update(extra)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "o.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return vo.load_overlay(p)


EXT = {"concept": "Device Compatibility", "status": "EXTEND existing", "trigger_phrases": ["VoLTE", "HD Voice"]}
NEW = {"concept": "IoT & M2M Services", "status": "NEW", "trigger_phrases": ["IoT", "M2M"]}


class TestBodyTextSections(unittest.TestCase):

    def test_related_sections_are_removed_but_neighbouring_sections_stay(self):
        text = ("## Summary\nKeep this VoLTE sentence.\n\n### Related Information\n\nRelated documents referenced in metadata: Policy_C19_privacy_policy.\n\n"
                "## Next Steps\nKeep this too.\n\n## References\n\nNo directly linked documents.\n")
        body = ce.body_text(doc(text))
        self.assertIn("Keep this VoLTE sentence", body)
        self.assertIn("Keep this too", body)
        self.assertNotIn("Policy_C19", body)
        self.assertNotIn("No directly linked", body)

    def test_related_documents_section_at_the_end_is_removed(self):
        body = ce.body_text(doc("## Body\ntext\n\n## Related Documents\n\nRelated documents: FAQ_C02_001."))
        self.assertIn("text", body)
        self.assertNotIn("FAQ_C02_001", body)

    def test_a_similar_heading_is_not_removed(self):
        body = ce.body_text(doc("## Related Issues\n\n- Repeated occurrences may indicate an upstream problem.\n"))
        self.assertIn("Repeated occurrences", body)


class TestOverlayMentions(unittest.TestCase):

    def test_phrases_match_case_insensitively_with_boundaries(self):
        ov = overlay([EXT, NEW])
        recs = ce.extract_concept_mentions(doc("Why doesn't volte/HD voice work? Also iot devices."), families=(), overlay=ov)
        by = {r["concept"]: r for r in recs}
        self.assertEqual(set(by), {"Device Compatibility", "IoT & M2M Services"})
        self.assertEqual(sorted(by["Device Compatibility"]["matched_terms"]), ["hd voice", "volte"])
        self.assertEqual(ce.extract_concept_mentions(doc("They revolted against patriotic riot."), families=(), overlay=ov), [])

    def test_hyphen_and_slash_boundaries(self):
        ov = overlay([{"concept": "IoT & M2M Services", "status": "NEW", "trigger_phrases": ["NB-IoT", "M2M"]}])
        self.assertEqual(len(ce.extract_concept_mentions(doc("Supports NB-IoT, and IoT/M2M fleets."), families=(), overlay=ov)), 1)
        self.assertEqual(ce.extract_concept_mentions(doc("xM2M and M2Mx"), families=(), overlay=ov), [])

    def test_header_footer_and_related_sections_do_not_count(self):
        text = ("**Document ID:** X\n**Category:** C24 – IoT & M2M Services\n\n## Body\nNothing relevant.\n\n### Related Information\n\n"
                "IoT references here.\n\nTopic: IoT & M2M Services")
        self.assertEqual(ce.extract_concept_mentions(doc(text), families=(), overlay=overlay([NEW])), [])

    def test_generic_template_words_never_match(self):
        ov = overlay([EXT])
        self.assertEqual(ce.extract_concept_mentions(doc("There was an outage; troubleshooting the bill."), families=(), overlay=ov), [])
        self.assertEqual(ce.extract_concept_mentions(doc("outage"), families=("Network Outages",), overlay=ov), [])   # name is not a trigger either

    def test_record_carries_evidence_phrase_field_and_snippet(self):
        r = ce.extract_concept_mentions(doc("Question: Why does VoLTE fail?\n\nAnswer: Check the IMEI."), families=(), overlay=overlay([EXT]))[0]
        self.assertEqual((r["concept"], r["concept_type"], r["evidence_field"]), ("Device Compatibility", "Concept", "body"))
        self.assertEqual(r["evidence_span"].lower(), "volte")
        self.assertIn("volte", r["evidence"].lower())
        self.assertEqual(r["source"], "vocabulary_extension")

    def test_family_and_overlay_hits_merge_into_one_record(self):
        recs = ce.extract_concept_mentions(doc("Device Compatibility and VoLTE."), families=("Device Compatibility",), overlay=overlay([EXT]))
        self.assertEqual(len(recs), 1)
        self.assertEqual(sorted(recs[0]["matched_terms"]), ["device compatibility", "volte"])

    def test_edges_for_extend_and_new_concepts(self):
        with mock.patch.object(ce, "active_overlay", lambda: overlay([EXT, NEW])):
            res = ce.extract_content([doc("VoLTE on IoT meters.")], families=())
        edges = {(e["source"], e["target"], e["type"]) for e in res["concept_mention_edges"]}
        self.assertEqual(edges, {("Document::FAQ_X_001", "Concept::Device Compatibility", "MENTIONS_CONCEPT"),
                                 ("Document::FAQ_X_001", "Concept::IoT & M2M Services", "MENTIONS_CONCEPT")})
        for e in res["concept_mention_edges"]:
            self.assertEqual(e["properties"]["evidence_field"], "body")
            self.assertTrue(e["properties"]["evidence_span"])
            self.assertEqual(e["properties"]["rule"], "vocabulary_overlay")
        self.assertEqual(res["stats"]["documents_with_any_content_concept"], 1)

    def test_overlay_can_be_switched_off(self):
        with mock.patch.object(ce, "OVERLAY_ENABLED", False):
            res = ce.extract_content(load_documents(), families=())
        self.assertEqual(res["concept_mention_edges"], [])

    def test_dropped_concepts_and_phrases_do_not_match(self):
        ov = overlay([EXT, NEW], dropped={"IoT & M2M Services": "fails (b)"}, dropped_phrases={"Device Compatibility": {"HD Voice": "hub phrase"}})
        recs = ce.extract_concept_mentions(doc("IoT, HD Voice and VoLTE."), families=(), overlay=ov)
        self.assertEqual([(r["concept"], r["matched_terms"]) for r in recs], [("Device Compatibility", ["volte"])])

    def test_earlier_name_family_edges_are_unchanged_by_the_new_body_rule(self):
        with mock.patch.object(ce, "OVERLAY_ENABLED", False):
            res = ce.extract_content(load_documents())
        pairs = sorted((e["source"].split("::", 1)[1], e["target"].split("::", 1)[1]) for e in res["concept_mention_edges"])
        self.assertEqual(pairs, sorted([
            ("FAQ_C09_017", "Device Compatibility"), ("FAQ_C12_023", "Device Compatibility"),
            ("FAQ_C08_015", "Network Coverage"), ("FAQ_C11_022", "Network Coverage"), ("KB_C08_outage_status_check", "Network Coverage"),
            ("RCA_INC_2026_0142", "Network Coverage"), ("SOP_C08_OUTAGE_MANAGEMENT", "Network Coverage")]))


class TestConceptNodes(unittest.TestCase):

    def nodes_for(self, ov):
        from knowledge_graph.entity_extractor import extract_entities
        docs = load_documents()
        nodes = extract_entities(docs)["nodes"] + ce.extract_content(docs)["nodes"]          # entity + content nodes, as build_full passes them
        with mock.patch.object(ce, "active_overlay", lambda: ov):
            return build_concept_metadata(nodes)

    def test_new_concepts_become_nodes_with_source_and_the_shared_23_are_unchanged(self):
        meta = self.nodes_for(overlay([EXT, NEW]))
        shared = [n for n in meta["nodes"] if "source" not in n["properties"]]
        added = [n for n in meta["nodes"] if n["properties"].get("source") == "vocabulary_extension"]
        self.assertEqual(len(shared), 23)
        self.assertEqual([n["key"] for n in added], ["IoT & M2M Services"])
        n = added[0]
        self.assertEqual((n["id"], n["label"]), ("Concept::IoT & M2M Services", "Concept"))
        self.assertEqual(n["properties"]["tables"], [])
        self.assertEqual(len(meta["edges"]), 33)                         # EXPRESSES_CONCEPT edges are untouched

    def test_extend_concepts_add_no_node_and_dropped_new_concepts_add_none(self):
        self.assertEqual(len(self.nodes_for(overlay([EXT]))["nodes"]), 23)
        self.assertEqual(len(self.nodes_for(overlay([EXT, NEW], dropped={"IoT & M2M Services": "x"}))["nodes"]), 23)

    def test_real_overlay_in_the_full_graph_every_mention_edge_has_both_endpoints(self):
        from knowledge_graph.graph_builder import build_full
        b = build_full()
        ids = set(b["graph"].nodes)
        for e in b["concepts"]["mention_edges"]:
            self.assertIn(e["source"], ids)
            self.assertIn(e["target"], ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
