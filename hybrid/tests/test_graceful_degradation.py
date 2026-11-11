"""
Step 1 of the KG fixes (tests first): run_hybrid_query and answer_question must never raise on a missing asset.
One test per scenario of table C of the audit (docs/E13_kg_audit.md), with mocks and tmp dirs only - no network, no models.

  graph.json missing / corrupt        -> empty graph and link lists, trace note "graph unavailable: <reason>"; loaded lazily,
                                         and not at all when GRAPH_ENABLED and LINKS_ENABLED are both false
  models or FAISS index missing       -> unstructured side returns nothing, trace note "vector retrieval unavailable: <reason>";
                                         the answer layer says it cannot answer from documents and invents nothing
  structured DB missing + customer id -> structured side executed=False with a note; documents still run
  CrossEncoder cannot load            -> existing graceful FALLBACK (kept)
  empty graph list / unknown concept  -> fine
  the clear error text and the setup_check command are kept
"""

import functools
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pipeline  # noqa: E402
import retrievers  # noqa: E402
import structured_adapter  # noqa: E402
from answer import answer_question  # noqa: E402
from knowledge_graph import graph_augmented_retrieval as kg  # noqa: E402

REAL_LOADER = kg.load_graph_index   # captured before any test patches the module attribute

MISSING_GRAPH = ("{path} not found. Build the graph first: python -m knowledge_graph.graph_builder")
POLICY_Q = "How do refunds to my bank account work?"
BOTH_Q = "My KYC is showing pending - does that mean my number will get disconnected, and what do I do?"
PERSONAL_Q = "Did my last recharge go through?"


class FakeRetriever:
    def search(self, question, depth=10):
        return [{"document_id": f"DOC_{i}", "chunk_id": f"DOC_{i}_chunk_000", "title": f"title {i}",
                 "category": "C20", "score": 1.0 - i / 100} for i in range(1, 7)]


class FakePersonA:
    @staticmethod
    def load_chunk_text(chunk_id):
        return f"Answer: Refunds to source generally reflect within 5-7 working days. ({chunk_id})"


class FakeCorpus:
    title_by_doc = {}

    @staticmethod
    def first_chunk(doc):
        return f"{doc}_chunk_000"


class Scorer:
    def predict(self, pairs):
        return [float(len(p[1])) for p in pairs]


def fake_vector_context():
    return {"person_a": FakePersonA, "retriever": FakeRetriever(), "corpus": FakeCorpus}


def raising(exc):
    def _raise(*args, **kwargs):
        raise exc
    return _raise


class Base(unittest.TestCase):

    def setUp(self):
        retrievers._graph_index_cache = None      # the loader caches only a successful load
        patcher = mock.patch.object(retrievers, "load_vector_context", fake_vector_context)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(setattr, retrievers, "_graph_index_cache", None)

    def run_query(self, question=POLICY_Q, customer=None, **kw):
        return pipeline.run_hybrid_query(question, customer, model=Scorer(), **kw)

    def missing_graph(self):
        return mock.patch.object(kg, "load_graph_index",
                                 raising(FileNotFoundError(MISSING_GRAPH.format(path="X/graph.json"))))


class TestGraphUnavailable(Base):

    def test_missing_graph_json_gives_empty_lists_and_a_trace_note_but_documents_still_run(self):
        with self.missing_graph():
            out = self.run_query()
        t = out["trace"]
        self.assertTrue(out["documents"])
        self.assertTrue(t["graph"].startswith("graph unavailable: "))
        self.assertIn("python -m knowledge_graph.graph_builder", t["graph"])      # the clear fix command is kept
        self.assertEqual(t["links"], "links unavailable: graph unavailable")
        self.assertEqual(t["linked_documents"], [])
        self.assertTrue(all("graph" not in d["fusion_sources"] and "links" not in d["fusion_sources"] for d in out["documents"]))

    def test_graph_is_not_even_loaded_when_graph_and_links_are_both_off(self):
        loader = mock.Mock(side_effect=FileNotFoundError("must not be called"))
        with mock.patch.object(kg, "load_graph_index", loader):
            out = self.run_query(graph_enabled=False, links_enabled=False)
        loader.assert_not_called()
        self.assertTrue(out["documents"])
        self.assertEqual(out["trace"]["graph"], "graph disabled by config")
        self.assertEqual(out["trace"]["links"], "links disabled by config")

    def test_graph_is_loaded_lazily_when_only_links_are_on(self):
        loader = mock.Mock(side_effect=FileNotFoundError("not built"))
        with mock.patch.object(kg, "load_graph_index", loader):
            out = self.run_query(graph_enabled=False, links_enabled=True)
        self.assertEqual(loader.call_count, 1)
        self.assertTrue(out["trace"]["links"].startswith("links unavailable"))
        self.assertTrue(out["documents"])

    def test_corrupt_graph_json(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "graph.json"
            bad.write_text('{"nodes": [', encoding="utf-8")
            with mock.patch.object(kg, "load_graph_index", functools.partial(REAL_LOADER, bad)):
                out = self.run_query()
        self.assertTrue(out["documents"])
        self.assertTrue(out["trace"]["graph"].startswith("graph unavailable: JSONDecodeError"), out["trace"]["graph"])

    def test_malformed_graph_structure(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "graph.json"
            bad.write_text(json.dumps({"nodes": [{"id": "x"}], "edges": []}), encoding="utf-8")   # nodes lack label/key
            with mock.patch.object(kg, "load_graph_index", functools.partial(REAL_LOADER, bad)):
                out = self.run_query()
        self.assertTrue(out["documents"])
        self.assertTrue(out["trace"]["graph"].startswith("graph unavailable: "))

    def test_answer_question_without_graph_json_does_not_raise(self):
        with self.missing_graph():
            out = answer_question(POLICY_Q, None, pipeline=functools.partial(pipeline.run_hybrid_query, model=Scorer()))
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertIn("[D1]", out["answer"])
        self.assertEqual(out["mode"], "extractive")

    def test_empty_graph_list_is_fine(self):
        with mock.patch.object(kg, "load_graph_index", lambda *a, **k: kg.GraphIndex()):
            out = self.run_query()
        self.assertEqual(out["trace"]["graph"], "graph enabled")
        self.assertEqual(out["trace"]["linked_documents"], [])
        self.assertTrue(out["documents"])

    def test_unknown_concept_question_is_fine(self):
        with mock.patch.object(kg, "load_graph_index", lambda *a, **k: kg.GraphIndex()):
            out = self.run_query("zzz qqq plain words nothing telecom")
        self.assertTrue(out["documents"])
        self.assertEqual(out["trace"]["graph_weight"], 0.0)
        self.assertEqual(kg.graph_expand(["NO_SUCH_DOC"], kg.GraphIndex()), [])
        self.assertEqual(kg.related_neighbours(["NO_SUCH_DOC"], kg.GraphIndex()), [])

    def test_loader_error_text_still_names_the_fix_command(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError) as ctx:
                kg.load_graph_index(Path(d) / "graph.json")
        self.assertIn("python -m knowledge_graph.graph_builder", str(ctx.exception))
        # the safe wrapper never raises: it returns (index, None) or (None, reason that names the fix command)
        index, reason = retrievers.get_graph_index_safe()
        self.assertTrue(index is not None or "python -m knowledge_graph.graph_builder" in reason)

    def test_setup_check_command_is_kept(self):
        import setup_check
        rows = {name: fix for name, ok, detail, fix in setup_check.check(Path("/nonexistent"), Path("/nonexistent"))}
        self.assertIn("python -m knowledge_graph.graph_builder", rows["graph.json"])


class TestVectorRetrievalUnavailable(Base):

    def run_without_vector(self, exc, question=POLICY_Q, customer=None):
        with mock.patch.object(retrievers, "load_vector_context", raising(exc)):
            return pipeline.run_hybrid_query(question, customer, model=Scorer())

    def test_missing_models(self):
        out = self.run_without_vector(OSError("We couldn't connect to 'https://huggingface.co' to load the files"))
        self.assertEqual(out["documents"], [])
        self.assertTrue(out["trace"]["vector"].startswith("vector retrieval unavailable: OSError"), out["trace"]["vector"])
        self.assertIn("document_retrieval_unavailable", out["blocked"])
        self.assertFalse(out["trace"]["documents_ran"])

    def test_missing_faiss_index(self):
        out = self.run_without_vector(RuntimeError("could not open data\\vectorstore\\faiss.index for reading"))
        self.assertEqual(out["documents"], [])
        self.assertIn("faiss.index", out["trace"]["vector"])
        self.assertTrue(out["trace"]["vector"].startswith("vector retrieval unavailable: RuntimeError"))

    def test_answer_says_it_cannot_answer_from_documents_and_invents_nothing(self):
        with mock.patch.object(retrievers, "load_vector_context", raising(OSError("no models"))):
            out = answer_question(POLICY_Q, None, pipeline=functools.partial(pipeline.run_hybrid_query, model=Scorer()))
        self.assertIn("document retrieval is unavailable", out["answer"])
        self.assertEqual(out["citations"], {})
        self.assertNotIn("[D", out["answer"])
        self.assertFalse(any(ch.isdigit() for ch in out["answer"]))
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])
        self.assertIn("document_retrieval_unavailable", out["notices"])

    def test_structured_facts_survive_a_document_outage(self):
        with mock.patch.object(retrievers, "load_vector_context", raising(OSError("no models"))):
            out = pipeline.run_hybrid_query(BOTH_Q, 1042, model=Scorer())
        self.assertTrue(out["facts"])                      # the customer's own facts are unaffected
        self.assertEqual(out["documents"], [])

    def test_crossencoder_failure_is_still_a_graceful_fallback(self):
        import rerank
        with mock.patch.object(rerank, "_load_model", side_effect=OSError("cannot load cross-encoder")), \
                self.assertWarns(RuntimeWarning):
            out = pipeline.run_hybrid_query(POLICY_Q, None)          # real rerank path, model unavailable
        self.assertTrue(out["documents"])
        self.assertTrue(out["trace"]["rerank_status"].startswith("FALLBACK"))


class TestStructuredDbUnavailable(Base):

    def db_missing(self):
        return mock.patch.object(structured_adapter, "open_readonly",
                                 raising(sqlite3.OperationalError("unable to open database file")))

    def test_real_open_readonly_raises_for_a_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(sqlite3.OperationalError):
                structured_adapter.open_readonly(os.path.join(d, "missing.db"))

    def test_policy_question_with_customer_id_does_not_crash_in_the_router(self):
        with self.db_missing():
            out = self.run_query(POLICY_Q, 1042)
        self.assertTrue(out["documents"])
        self.assertEqual(out["facts"], [])

    def test_personal_question_with_customer_id_returns_executed_false_and_a_note(self):
        with self.db_missing():
            out = self.run_query(PERSONAL_Q, 1042)
        t = out["trace"]
        self.assertEqual(out["facts"], [])
        self.assertIs(t["structured_executed"], False)
        self.assertIn("structured data unavailable", t["structured_note"])
        self.assertIn("unable to open database file", t["structured_note"])
        self.assertIn("structured_unavailable", out["blocked"])

    def test_documents_still_run_for_a_both_route_question(self):
        with self.db_missing():
            out = self.run_query(BOTH_Q, 1042)
        self.assertTrue(out["documents"])
        self.assertIs(out["trace"]["structured_executed"], False)

    def test_answer_layer_says_it_cannot_look_up_the_account_and_invents_no_values(self):
        with self.db_missing():
            out = answer_question(BOTH_Q, 1042, pipeline=functools.partial(pipeline.run_hybrid_query, model=Scorer()))
        self.assertIn("account database is unavailable", out["answer"])
        self.assertNotIn("[F", out["answer"])
        self.assertIn("structured_unavailable", out["notices"])
        self.assertTrue(out["verifier"]["ok"], out["verifier"]["problems"])

    def test_no_customer_id_never_touches_the_database(self):
        with self.db_missing():
            out = self.run_query(PERSONAL_Q, None)
        self.assertEqual(out["route_plan"]["outcome"], "needs_identity")
        self.assertTrue(out["documents"])
        self.assertNotIn("structured_executed", out["trace"])


class TestFreshCloneEndToEnd(unittest.TestCase):
    """The 7 end-to-end tests that failed in a fresh clone (no graph.json) now degrade instead of raising:
    with a missing graph they still return documents and a trace note, so their assertions on facts/documents/outcomes hold."""

    def test_default_context_never_requires_the_graph(self):
        import inspect
        src = inspect.getsource(retrievers.load_vector_context)
        self.assertNotIn("load_graph_index", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
