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
