"""
Tests for knowledge_graph.graph_augmented_retrieval.graph_expand.

* golden: the legacy (V0) output recorded BEFORE the hardening change is reproduced exactly;
* hardening: hub cut, specificity weighting, caps, determinism (Part 1c of the KG hardening task).
"""

import json
import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from knowledge_graph.graph_augmented_retrieval import (  # noqa: E402
    DEFAULT_BRIDGES, GraphIndex, graph_expand, load_graph_index)

GOLDEN = REPO_ROOT / "knowledge_graph" / "tests_data" / "graph_expand_golden.json"


class TestLegacyGolden(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = load_graph_index()
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]

    def test_golden_has_the_required_coverage(self):
        self.assertGreaterEqual(len(self.golden), 8)
        self.assertTrue(any(c["seeds"] == ["FAQ_C17_034"] for c in self.golden))
        self.assertTrue(any(len(c["seeds"]) == 5 for c in self.golden))
        self.assertTrue(any(len(c["seeds"]) == 1 for c in self.golden))

    def test_v0_reproduces_the_recorded_output_exactly(self):
        for case in self.golden:
            out = graph_expand(case["seeds"], self.index, bridges=case["bridges"], limit=case["limit"])
            self.assertEqual(out, case["output"], case["seeds"])

    def test_default_arguments_equal_explicit_legacy_arguments(self):
        for case in self.golden:
            if case["bridges"] == list(DEFAULT_BRIDGES) and case["limit"] == 20:
                self.assertEqual(graph_expand(case["seeds"], self.index), case["output"])
                self.assertEqual(
                    graph_expand(case["seeds"], self.index, hub_fraction=None, specificity=False,
                                 max_documents=None, allowed_labels=None), case["output"])


class TestHardening(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = load_graph_index()
        cls.n = cls.index.document_count

    def concept_df(self, key):
        label, concept = key.split(":", 1)
        return self.index.document_frequency(label, concept)

    def test_document_count_and_frequency(self):
        self.assertGreaterEqual(self.n, 140)
        self.assertEqual(self.index.document_frequency("VerificationMethod", "OTP"), 47)
        self.assertEqual(self.index.document_frequency("Service", "Complaint Registration"), 45)
        self.assertEqual(self.index.document_frequency("Service", "no such concept"), 0)

    def test_hub_cut_drops_every_concept_above_the_threshold(self):
        threshold = 0.10 * self.n
        for seeds in (["FAQ_C17_034"], ["MAN_APP_001", "SOP_C13_APP_ACCESS_ISSUES", "FAQ_C13_025"]):
            legacy = graph_expand(seeds, self.index, limit=500)
            cut = graph_expand(seeds, self.index, limit=500, hub_fraction=0.10)
            legacy_concepts = {c for r in legacy for c in r["shared_concepts"]}
            self.assertTrue(any(self.concept_df(c) > threshold for c in legacy_concepts))  # the test can fail
            for row in cut:
                for concept in row["shared_concepts"]:
                    self.assertLessEqual(self.concept_df(concept), threshold, concept)
            self.assertLessEqual(len(cut), len(legacy))

    def test_specificity_ranks_a_rare_shared_concept_above_a_hub(self):
        # tiny synthetic graph: B shares the hub with A; C shares a rare concept with A
        ix = GraphIndex()
        docs = {"A": {"Service": {"hub", "rare"}}, "B": {"Service": {"hub"}}, "C": {"Service": {"rare"}}}
        for i in range(10):
            docs[f"X{i}"] = {"Service": {"hub"}}
        for doc, labels in docs.items():
            ix.document_concepts[doc] = labels
            for label, concepts in labels.items():
                for concept in concepts:
                    ix.concept_documents.setdefault(label, {}).setdefault(concept, set()).add(doc)
        legacy = graph_expand(["A"], ix, bridges=["Service"], limit=50)
        self.assertEqual(legacy[0]["document_id"], "B")           # tie on score 1.0 -> id order: B before C ... and X*
        weighted = graph_expand(["A"], ix, bridges=["Service"], limit=50, specificity=True)
        self.assertEqual(weighted[0]["document_id"], "C")         # rare concept now wins
        self.assertGreater(weighted[0]["graph_score"], weighted[1]["graph_score"])
        self.assertAlmostEqual(weighted[0]["graph_score"], round(math.log(ix.document_count / 2), 6), places=6)

    def test_caps_are_respected(self):
        seeds = ["FAQ_C17_034", "KB_C17_kyc_reverification", "SOP_C17_KYC_VERIFICATION"]
        self.assertGreater(len(graph_expand(seeds, self.index, limit=100)), 10)
        for cap in (3, 5, 10):
            self.assertEqual(len(graph_expand(seeds, self.index, limit=100, max_documents=cap)), cap)
        self.assertEqual(len(graph_expand(seeds, self.index, limit=4, max_documents=10)), 4)  # limit still applies
        # the capped list is the head of the uncapped one
        full = graph_expand(seeds, self.index, limit=100, hub_fraction=0.10, specificity=True)
        capped = graph_expand(seeds, self.index, limit=100, hub_fraction=0.10, specificity=True, max_documents=5)
        self.assertEqual(capped, full[:5])

    def test_allowed_labels_restrict_the_bridges(self):
        out = graph_expand(["FAQ_C17_034"], self.index, limit=100, allowed_labels=["Service", "VerificationMethod", "Tag"])
        self.assertTrue(out)
        for row in out:
            for concept in row["shared_concepts"]:
                self.assertIn(concept.split(":", 1)[0], {"Service", "VerificationMethod", "Tag"})
        legacy_labels = {c.split(":", 1)[0] for r in graph_expand(["FAQ_C17_034"], self.index, limit=100)
                         for c in r["shared_concepts"]}
        self.assertIn("Channel", legacy_labels)                    # the restriction really removed something

    def test_empty_and_unknown_seeds_return_nothing(self):
        self.assertEqual(graph_expand([], self.index), [])
        self.assertEqual(graph_expand(["NO_SUCH_DOCUMENT"], self.index), [])
        self.assertEqual(graph_expand(["NO_SUCH_DOCUMENT"], self.index, hub_fraction=0.1, specificity=True,
                                      max_documents=3), [])

    def test_deterministic_and_ordered(self):
        seeds = ["FAQ_C17_034", "MAN_APP_001", "TRX_007"]
        first = graph_expand(seeds, self.index, hub_fraction=0.10, specificity=True, max_documents=10)
        for _ in range(3):
            self.assertEqual(graph_expand(seeds, self.index, hub_fraction=0.10, specificity=True, max_documents=10), first)
        keys = [(-r["graph_score"], -r["shared_count"], r["document_id"]) for r in first]
        self.assertEqual(keys, sorted(keys))

    def test_seeds_are_never_returned_as_their_own_candidates_unless_shared_with_another_seed(self):
        out = graph_expand(["FAQ_C17_034"], self.index, limit=500)
        self.assertNotIn("FAQ_C17_034", [r["document_id"] for r in out])
