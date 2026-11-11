"""
KG fixes 2, step 2 (tests first): MENTIONS_CONCEPT edges reach graph.json, endpoints exist, builds stay byte-identical, and retrieval
(graph_expand, related_neighbours) and Person A's RELATED_TO reader are unaffected by them.
The families are patched in the test; the shipped tuple is whatever the per-family acceptance check kept.
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
from knowledge_graph.graph_augmented_retrieval import graph_expand, load_graph_index, related_neighbours  # noqa: E402
from knowledge_graph.graph_builder import build_full, save_graph  # noqa: E402

FAMILIES = ("Device Compatibility", "Network Coverage")


def build_to(out, families):
    with mock.patch.object(ce, "CONCEPT_NAME_FAMILIES", families):
        b = build_full()
    save_graph(b["graph"], b["entities"], b["relationships"], b["content"], output_dir=Path(out), concepts=b["concepts"])
    return b, json.loads((Path(out) / "graph.json").read_text(encoding="utf-8"))


class TestMentionEdgesInTheGraph(unittest.TestCase):

    def test_edges_are_in_graph_json_with_existing_endpoints(self):
        with tempfile.TemporaryDirectory() as d0, tempfile.TemporaryDirectory() as d1:
            _, base = build_to(d0, ())
            built, withm = build_to(d1, FAMILIES)
        added = [e for e in withm["edges"] if e["type"] == "MENTIONS_CONCEPT"]
        self.assertTrue(added)
        self.assertEqual(len(withm["edges"]) - len(base["edges"]), len(added))
        self.assertEqual(len(withm["nodes"]), len(base["nodes"]))           # no new nodes: the Concept nodes already exist
        ids = {n["id"] for n in withm["nodes"]}
        for e in added:
            self.assertIn(e["source"], ids)
            self.assertIn(e["target"], ids)
            self.assertTrue(e["target"].startswith("Concept::"))
            self.assertTrue(e["properties"]["evidence_span"])
        self.assertEqual(built["graph"].number_of_edges(), len(withm["edges"]))

    def test_no_families_means_no_mention_edges(self):
        with tempfile.TemporaryDirectory() as d:
            _, payload = build_to(d, ())
        self.assertEqual(sum(1 for e in payload["edges"] if e["type"] == "MENTIONS_CONCEPT"), 0)

    def test_two_builds_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            build_to(a, FAMILIES)
            build_to(b, FAMILIES)
            for name in ("graph.json", "nodes.json", "edges.json", "content_extraction.json"):
                self.assertEqual((Path(a) / name).read_bytes(), (Path(b) / name).read_bytes(), name)

    def test_retrieval_and_person_a_reader_ignore_the_new_edges(self):
        with tempfile.TemporaryDirectory() as d0, tempfile.TemporaryDirectory() as d1:
            build_to(d0, ())
            _, payload = build_to(d1, FAMILIES)
            a, b = load_graph_index(Path(d0) / "graph.json"), load_graph_index(Path(d1) / "graph.json")
        for seeds in (["FAQ_C17_034"], ["KB_C17_kyc_reverification", "SOP_C17_KYC_VERIFICATION"], ["FAQ_C12_023", "MAN_DEVICE_VOLTE_001"]):
            self.assertEqual(graph_expand(seeds, a), graph_expand(seeds, b))
            self.assertEqual(related_neighbours(seeds, a), related_neighbours(seeds, b))
        self.assertEqual(sum(1 for e in payload["edges"] if e["type"] == "RELATED_TO"), 84)

    def test_stats_are_recorded(self):
        with mock.patch.object(ce, "CONCEPT_NAME_FAMILIES", FAMILIES):
            b = build_full()
        self.assertGreater(b["content"]["stats"]["concept_mention_edges"], 0)
        self.assertGreater(b["content"]["stats"]["documents_with_any_content_concept"], 125)


if __name__ == "__main__":
    unittest.main(verbosity=2)
