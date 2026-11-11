"""
Step 2 of the KG fixes (tests first): one link mechanism. run_hybrid_query calls build_candidates(use_related_links=False);
the only source of linked documents is the separate link list from link_candidates_for (top-3 seeds, cap 2).
The audit found the same neighbours entering twice: top-5-seed links inside the (gate-dependent) graph list AND the link list.
Pre-declared rule and the 52-question measurement: docs/E13_kg_fixes.md (verdict KEEP: no dev question changed).
No models, no graph.json: a tiny synthetic graph index and stubs.
"""

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pipeline  # noqa: E402
import retrievers  # noqa: E402
from knowledge_graph.graph_augmented_retrieval import GraphIndex  # noqa: E402


def tiny_index():
    """A links to LINKED; A and B share the Service concept 'Refund' with CONCEPT_ONLY."""
    ix = GraphIndex()
    ix.known_documents = {"A", "B", "LINKED", "CONCEPT_ONLY"}
    for doc, concepts in {"A": {"Refund"}, "B": {"Refund"}, "CONCEPT_ONLY": {"Refund"}, "LINKED": set()}.items():
        ix.document_concepts[doc] = {"Service": set(concepts)} if concepts else {}
        for c in concepts:
            ix.concept_documents.setdefault("Service", {}).setdefault(c, set()).add(doc)
    ix.related = {"A": {"LINKED"}, "LINKED": {"A"}}
    return ix


class FakeRetriever:
    def search(self, question, depth=10):
        return [{"document_id": d, "chunk_id": f"{d}_chunk_000", "title": d, "category": "", "score": s}
                for d, s in (("A", 0.9), ("B", 0.8))]


class FakePersonA:
    @staticmethod
    def load_chunk_text(chunk_id):
        return f"text {chunk_id}"


class FakeCorpus:
    title_by_doc = {}

    @staticmethod
    def first_chunk(doc):
        return f"{doc}_chunk_000"


class Scorer:
    def predict(self, pairs):
        return [0.0] * len(pairs)


class TestOneLinkMechanism(unittest.TestCase):

    def test_pipeline_constant_and_call(self):
        self.assertIs(pipeline.USE_RELATED_LINKS, False)
        seen = {}

        def fake_build(question, *a, **kw):
            seen.update(kw)
            return [], [], 0

        with mock.patch.object(retrievers, "build_candidates", fake_build), \
                mock.patch.object(retrievers, "get_graph_index_safe", lambda: (tiny_index(), None)), \
                mock.patch.object(retrievers, "load_vector_context",
                                  lambda: {"corpus": FakeCorpus, "person_a": FakePersonA}), \
                mock.patch.object(pipeline, "run_hybrid_retrieval", lambda *a, **k: []):
            pipeline.run_hybrid_query("How do refunds work?", None)
        self.assertIs(seen.get("use_related_links"), False)

    def test_graph_list_has_no_linked_documents_when_use_related_links_is_false(self):
        ix = tiny_index()
        vector, graph, _ = retrievers.build_candidates("q", FakeRetriever(), ix, FakeCorpus, FakePersonA,
                                                       use_related_links=False, graph_enabled=True)
        graph_docs = [c["metadata"]["document_id"] for c in graph]
        self.assertNotIn("LINKED", graph_docs)
        self.assertIn("CONCEPT_ONLY", graph_docs)       # concept candidates are untouched
        _, graph_old, _ = retrievers.build_candidates("q", FakeRetriever(), ix, FakeCorpus, FakePersonA,
                                                      use_related_links=True, graph_enabled=True)
        self.assertEqual([c["metadata"]["document_id"] for c in graph_old][0], "LINKED")   # the old, duplicated path

    def test_end_to_end_a_linked_document_enters_exactly_once_and_only_through_the_link_list(self):
        ix = tiny_index()
        with mock.patch.object(retrievers, "get_graph_index_safe", lambda: (ix, None)), \
                mock.patch.object(retrievers, "load_vector_context",
                                  lambda: {"retriever": FakeRetriever(), "corpus": FakeCorpus, "person_a": FakePersonA}):
            out = pipeline.run_hybrid_query("How do refunds work?", None, model=Scorer())
        docs = [d["metadata"]["document_id"] for d in out["documents"]]
        self.assertEqual(docs.count("LINKED"), 1)
        linked = next(d for d in out["documents"] if d["metadata"]["document_id"] == "LINKED")
        self.assertEqual(linked["fusion_sources"], ["links"])            # not ["links", "graph"]
        self.assertEqual(out["trace"]["linked_documents"], ["LINKED"])

    def test_with_the_gate_at_zero_the_link_list_still_works_and_nothing_else_leaks_in(self):
        ix = tiny_index()
        with mock.patch.object(retrievers, "get_graph_index_safe", lambda: (ix, None)), \
                mock.patch.object(retrievers, "load_vector_context",
                                  lambda: {"retriever": FakeRetriever(), "corpus": FakeCorpus, "person_a": FakePersonA}):
            out = pipeline.run_hybrid_query("zzz qqq plain words", None, model=Scorer())
        self.assertEqual(out["trace"]["graph_weight"], 0.0)
        docs = [d["metadata"]["document_id"] for d in out["documents"]]
        self.assertIn("LINKED", docs)
        self.assertNotIn("CONCEPT_ONLY", docs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
