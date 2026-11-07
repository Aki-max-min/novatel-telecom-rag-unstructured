"""The KG-hardening verdict (adoption FAIL) is wired as a config constant: the graph list is excluded from fusion in
run_hybrid_query unless switched on, and the trace says so. No models are loaded (retrieval is stubbed)."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pipeline  # noqa: E402
import retrievers  # noqa: E402

DOC = {"source": "unstructured", "record_id": "X_chunk_000", "dataset": "d", "category": "", "score": 1.0,
       "retrieval_method": "vector", "content": "text", "metadata": {"document_id": "X", "title": "t"}}


class TestGraphDefault(unittest.TestCase):

    def run_query(self, **kwargs):
        calls = {}

        def fake_build(question, *a, **kw):
            calls["graph_enabled"] = kw.get("graph_enabled", True)
            return [DOC], ([] if not kw.get("graph_enabled", True) else [dict(DOC, retrieval_method="graph")]), 0

        with mock.patch.object(retrievers, "build_candidates", fake_build), \
                mock.patch.object(pipeline, "run_hybrid_retrieval", lambda *a, **k: [dict(DOC, rerank_status="stub")]):
            out = pipeline.run_hybrid_query("How do refunds work?", None, **kwargs)
        return out, calls

    def test_default_is_off_and_recorded_in_the_trace(self):
        self.assertIs(pipeline.GRAPH_ENABLED, False)
        out, calls = self.run_query()
        self.assertIs(calls["graph_enabled"], False)
        self.assertEqual(out["trace"]["graph"], "graph disabled by config")

    def test_explicit_opt_in_turns_the_graph_back_on(self):
        out, calls = self.run_query(graph_enabled=True)
        self.assertIs(calls["graph_enabled"], True)
        self.assertEqual(out["trace"]["graph"], "graph enabled")

    def test_constant_is_read_at_call_time(self):
        with mock.patch.object(pipeline, "GRAPH_ENABLED", True):
            _, calls = self.run_query()
        self.assertIs(calls["graph_enabled"], True)

    def test_run_hybrid_retrieval_with_explicit_candidates_is_unchanged(self):
        vector = [dict(DOC, record_id="A_chunk_000", metadata={"document_id": "A"})]
        graph = [dict(DOC, record_id="B_chunk_000", metadata={"document_id": "B"}, retrieval_method="graph")]
        class Scorer:
            def predict(self, pairs):
                return [0.0] * len(pairs)
        out = pipeline.run_hybrid_retrieval("a question with no concept", vector, graph, model=Scorer())
        self.assertTrue(out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
