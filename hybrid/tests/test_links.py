"""
Link decoupling tests (written BEFORE the implementation): resolved RELATED_TO neighbours form their OWN ranked list in fusion,
independent of the gate graph weight, seeded by the top-3 vector documents only, capped at 2 linked documents.
No models are loaded: vector candidates are synthetic, chunk text/ids come from stubs; the real graph.json supplies the links.
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

from knowledge_graph.graph_builder import GRAPH_JSON_PATH  # noqa: E402

if not GRAPH_JSON_PATH.exists():
    raise unittest.SkipTest("graph.json missing: run python -m knowledge_graph.build_related_aliases "
                            "&& python -m knowledge_graph.graph_builder")

from fusion import fuse_and_select, fuse_candidates  # noqa: E402
from knowledge_graph.graph_augmented_retrieval import load_graph_index  # noqa: E402
from query_gate import classify_query, graph_weight  # noqa: E402
from retrievers import LINK_SEEDS, MAX_LINKED_DOCUMENTS, link_candidates_for  # noqa: E402

F1, F2, F3, F4 = "COV_NORTH_2026", "COV_SOUTH_2026", "EML_001", "EML_002"   # documents with no resolved links
NO_CONCEPT_QUESTION = "zzz plain words qqq"   # gate: no concept hint -> graph weight 0.0


class StubCorpus:
    def first_chunk(self, doc):
        return f"{doc}_chunk_000"


def make(doc, score=0.5, method="vector"):
    return {"source": "unstructured", "record_id": f"{doc}_chunk_000", "dataset": "d", "category": "", "score": score,
            "retrieval_method": method, "content": f"text of {doc}", "metadata": {"document_id": doc, "title": doc}}


def vector_list(*docs):
    return [make(d, 1.0 - i / 100) for i, d in enumerate(docs)]


def stub_text(chunk_id):
    return f"text of {chunk_id}"


class TestLinkCandidates(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = load_graph_index()

    def links(self, vector):
        return link_candidates_for(vector, self.index, StubCorpus(), stub_text)

    def ids(self, cands):
        return [c["metadata"]["document_id"] for c in cands]

    def test_filler_documents_really_have_no_links(self):
        for doc in (F1, F2, F3, F4):
            self.assertIn(doc, self.index.known_documents)
            self.assertNotIn(doc, self.index.related)

    def test_constants(self):
        self.assertEqual((LINK_SEEDS, MAX_LINKED_DOCUMENTS), (3, 2))

    def test_gate_weight_is_zero_for_the_test_question(self):
        self.assertEqual(graph_weight(classify_query(NO_CONCEPT_QUESTION)), 0.0)

    def test_linked_neighbour_of_a_top3_seed_enters_fusion_even_at_gate_weight_zero(self):
        vector = vector_list("RCA_INC_2026_0184", F1, F2, F3)
        links = self.links(vector)
        self.assertEqual(self.ids(links), ["INC_C13_INC_2026_0184"])
        self.assertTrue(all(c["retrieval_method"] == "link" for c in links))
        without = fuse_and_select(vector, [], NO_CONCEPT_QUESTION, top_k=20)
        self.assertNotIn("INC_C13_INC_2026_0184", self.ids(without))
        with_links = fuse_and_select(vector, [], NO_CONCEPT_QUESTION, top_k=20, link_candidates=links, link_weight=0.3)
        self.assertIn("INC_C13_INC_2026_0184", self.ids(with_links))
        row = next(c for c in with_links if c["metadata"]["document_id"] == "INC_C13_INC_2026_0184")
        self.assertEqual(row["fusion_sources"], ["links"])
        # UPDATED for the graph-fusion fix: links no longer carry a weighted score (old: 0.3/(60+1));
        # the linked document is appended after the 4 vector documents, so fusion_score = 1/(60+5)
        self.assertAlmostEqual(row["fusion_score"], 1 / (60 + 5), places=12)
        self.assertEqual(self.ids(with_links)[-1], "INC_C13_INC_2026_0184")

    def test_neighbour_of_a_rank4_or_lower_seed_does_not_enter(self):
        vector = vector_list(F1, F2, F3, "RCA_INC_2026_0184", F4)
        links = self.links(vector)
        self.assertEqual(links, [])
        fused = fuse_and_select(vector, [], NO_CONCEPT_QUESTION, top_k=20, link_candidates=links, link_weight=0.5)
        self.assertNotIn("INC_C13_INC_2026_0184", self.ids(fused))

    def test_a_linked_document_already_in_the_vector_list_is_not_added_again(self):
        vector = vector_list("RCA_INC_2026_0184", "INC_C13_INC_2026_0184", F1)
        self.assertEqual(self.links(vector), [])

    def test_cap_of_two_linked_documents_holds(self):
        by_degree = sorted(self.index.related, key=lambda d: (-len(self.index.related[d]), d))
        seeds = by_degree[:3]
        available = {n for s in seeds for n in self.index.related[s]} - set(seeds)
        self.assertGreater(len(available), 2, "the test needs more than 2 available neighbours")
        links = self.links(vector_list(*seeds, F4))
        self.assertEqual(len(links), 2)

    def test_link_list_is_ordered_by_seed_rank_then_id(self):
        by_degree = sorted(self.index.related, key=lambda d: (-len(self.index.related[d]), d))
        seeds = by_degree[:3]
        ids = self.ids(self.links(vector_list(*seeds)))
        first = sorted(self.index.related[seeds[0]] - set(seeds))
        if first:
            self.assertEqual(ids[0], first[0])

    def test_concept_list_is_untouched_by_links(self):
        vector = vector_list("RCA_INC_2026_0184", F1, F2, F3)
        graph = [make("KB_C13_selfcare_login_issues", 9.0, "graph"), make("SOP_C13_APP_ACCESS_ISSUES", 8.0, "graph")]
        links = self.links(vector)
        # UPDATED for the graph-fusion fix: fusion_score is positional (1/(k+position)), and the link block is
        # inserted between the vector and graph blocks, so graph-only documents shift position when links are added.
        # The surviving intent: the pre-existing documents keep their relative order and their sources exactly.
        for weight in (0.0, 0.5):
            base = fuse_candidates(vector, graph, weight)
            plus = fuse_candidates(vector, graph, weight, link_candidates=links, link_weight=0.3)
            base_keys = [c["fusion_doc_key"] for c in base]
            plus_keys = [c["fusion_doc_key"] for c in plus]
            self.assertEqual([k for k in plus_keys if k in set(base_keys)], base_keys)
            sources = {c["fusion_doc_key"]: c["fusion_sources"] for c in plus}
            for c in base:
                self.assertEqual(sources[c["fusion_doc_key"]], c["fusion_sources"], c["fusion_doc_key"])
            self.assertEqual(set(plus_keys) - set(base_keys), {"INC_C13_INC_2026_0184"})

    def test_links_off_output_is_identical_to_the_current_behaviour(self):
        vector = vector_list("A", "B", "C", "D")
        graph = [make("C", 5.0, "graph"), make("E", 3.0, "graph"), make("A", 1.0, "graph")]
        legacy = fuse_candidates(vector, graph, 0.5)
        self.assertEqual(fuse_candidates(vector, graph, 0.5, link_candidates=None, link_weight=0.3), legacy)
        self.assertEqual(fuse_candidates(vector, graph, 0.5, link_candidates=[], link_weight=0.3), legacy)
        self.assertEqual(fuse_candidates(vector, graph, 0.5, link_candidates=[make("Z", 1.0, "link")], link_weight=0.0),
                         legacy)
        self.assertEqual(fuse_and_select(vector, graph, "recharge plan", top_k=20),
                         fuse_and_select(vector, graph, "recharge plan", top_k=20, link_candidates=None))
        # the hand-checked worked example from the original fusion tests, unchanged
        scores = {c["fusion_doc_key"]: c["fusion_score"] for c in fuse_candidates(vector[:3], graph, 0.5)}
        # UPDATED for the graph-fusion fix: A no longer collects a graph bonus (old: 1/61 + 0.5/63); it keeps
        # vector position 1, so fusion_score = 1/61
        self.assertAlmostEqual(scores["A"], 1 / 61, places=15)


class TestPipelineSwitch(unittest.TestCase):

    def test_default_off_and_parameter_wins(self):
        import pipeline
        import retrievers
        self.assertIs(pipeline.LINKS_ENABLED, False)
        seen = {}

        def fake_links(vector, *args, **kwargs):
            seen["called"] = True
            return []

        doc = make("X")
        with mock.patch.object(retrievers, "build_candidates", lambda q, **k: ([doc], [], 0)), \
                mock.patch.object(retrievers, "link_candidates_for", fake_links), \
                mock.patch.object(retrievers, "load_context",
                                  lambda: {"graph_index": None, "corpus": None,
                                           "person_a": types.SimpleNamespace(load_chunk_text=stub_text)}), \
                mock.patch.object(pipeline, "run_hybrid_retrieval", lambda *a, **k: [dict(doc, rerank_status="stub")]):
            off = pipeline.run_hybrid_query("How do refunds work?", None)
            self.assertNotIn("called", seen)
            self.assertEqual(off["trace"]["links"], "links disabled by config")
            on = pipeline.run_hybrid_query("How do refunds work?", None, links_enabled=True)
            self.assertTrue(seen.get("called"))
            self.assertEqual(on["trace"]["links"], "links enabled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
