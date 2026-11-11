"""
Step 6 of the KG fixes (tests first): the graph profile is a switch, pipeline.GRAPH_KWARGS, passed to graph_expand through
build_candidates(graph_kwargs=...). Empty means the legacy profile (unchanged behaviour). Whether the hardened profile
(hub_fraction=0.05, specificity=True, max_documents=3) becomes the default is decided by the pre-declared rule in docs/E13_kg_fixes.md.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pipeline  # noqa: E402
import retrievers  # noqa: E402
from test_one_link_mechanism import FakeCorpus, FakePersonA, tiny_index  # noqa: E402

HARDENED = {"hub_fraction": 0.05, "specificity": True, "max_documents": 3}


class TestGraphKwargsSwitch(unittest.TestCase):

    def run_with(self, value):
        seen = {}

        def fake_build(question, *a, **kw):
            seen.update(kw)
            return [], [], 0

        with mock.patch.object(pipeline, "GRAPH_KWARGS", value), \
                mock.patch.object(retrievers, "build_candidates", fake_build), \
                mock.patch.object(retrievers, "get_graph_index_safe", lambda: (tiny_index(), None)), \
                mock.patch.object(retrievers, "load_vector_context",
                                  lambda: {"corpus": FakeCorpus, "person_a": FakePersonA}), \
                mock.patch.object(pipeline, "run_hybrid_retrieval", lambda *a, **k: []):
            pipeline.run_hybrid_query("How do refunds work?", None)
        return seen

    def test_constant_exists_and_is_a_dict(self):
        self.assertIsInstance(pipeline.GRAPH_KWARGS, dict)

    def test_empty_means_legacy_profile(self):
        self.assertIsNone(self.run_with({}).get("graph_kwargs"))

    def test_the_constant_reaches_build_candidates(self):
        self.assertEqual(self.run_with(dict(HARDENED)).get("graph_kwargs"), HARDENED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
