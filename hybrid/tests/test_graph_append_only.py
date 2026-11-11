"""
Graph-fusion fix tests (written BEFORE the code change): the graph is a candidate SOURCE, never a ranker.

Old behaviour (the bug, verified on Person A's v3 runs): every candidate scored 1/(60+rank) and graph-list members
got + graph_weight/(60+graph_rank) on top. Base scores are almost flat (rank 1 = 0.01639, rank 2 = 0.01613) while the
bonus is 0.0025 at weight 0.15 and 0.0082 at weight 0.5, so graph membership outranked relevance: at 0.15 a graph
member from vector rank 11 passed the rank-1 document, at 0.5 from rank 61.

New contract for hybrid/fusion.py::fuse_candidates (append-only):
  (a) with the graph list on, the relative order of the vector documents is identical to graph-off, for any weight > 0;
  (b) a document in BOTH the vector list and the graph/link list keeps exactly its vector position (no boost);
  (c) documents only in the link or graph list are appended AFTER all vector documents - links first, then graph
      candidates, each in their own list order, deduplicated by document key;
  (d) graph_weight is only an on/off switch: 0.15 and 0.5 give identical output; 0.0 excludes concept-graph candidates;
  (e) link candidates join the pool whatever the gate weight is; link_weight no longer changes the order;
  (f) the arithmetic regression cases from the bug report stay fixed.
No models and no graph.json are needed: all candidates are synthetic.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fusion import fuse_and_select, fuse_candidates  # noqa: E402
from query_gate import classify_query, graph_weight  # noqa: E402

NO_CONCEPT_QUESTION = "zzz plain words qqq"   # gate: no concept hint -> graph weight 0.0


def make(doc, score, method="vector"):
    return {"source": "unstructured", "record_id": f"{doc}_chunk_000", "dataset": "d", "category": "",
            "score": score, "retrieval_method": method, "content": f"text of {doc}",
            "metadata": {"document_id": doc, "title": doc}}


def vector_list(*docs):
    return [make(d, 1.0 - i / 100) for i, d in enumerate(docs)]


def graph_list(*docs):
    return [make(d, 9.0 - i, "graph") for i, d in enumerate(docs)]


def link_list(*docs):
    return [make(d, 1000.0 - i, "link") for i, d in enumerate(docs)]


def keys(out):
    return [c["fusion_doc_key"] for c in out]


class TestAppendOnly(unittest.TestCase):

    def test_a_vector_order_is_identical_with_graph_on_and_off(self):
        vector = vector_list("A", "B", "C", "D", "E")
        graph = graph_list("C", "X", "A", "Y")
        off = [k for k in keys(fuse_candidates(vector, graph, 0.0))]
        for weight in (0.15, 0.3, 0.5, 1.0):
            on = keys(fuse_candidates(vector, graph, weight))
            self.assertEqual([k for k in on if k in set(off)], off, f"weight={weight}")

    def test_b_membership_in_graph_or_links_gives_no_boost(self):
        vector = vector_list("A", "B", "C", "D")
        # C is graph rank 1, D is a link: neither may move
        out = fuse_candidates(vector, graph_list("C"), 0.5, link_candidates=link_list("D"), link_weight=0.5)
        self.assertEqual(keys(out)[:4], ["A", "B", "C", "D"])
        by_key = {c["fusion_doc_key"]: c for c in out}
        self.assertEqual(by_key["C"]["fusion_sources"], ["vector", "graph"])     # membership recorded, not scored
        self.assertEqual(by_key["D"]["fusion_sources"], ["vector", "links"])
        # the representative stays the vector chunk
        self.assertEqual(by_key["C"]["retrieval_method"], "vector")

    def test_c_new_documents_are_appended_links_first_then_graph_deduplicated(self):
        vector = vector_list("A", "B")
        graph = graph_list("G1", "A", "G2", "L1")     # L1 also appears in the link list -> dedup, links block wins
        links = link_list("L1", "L2")
        out = fuse_candidates(vector, graph, 0.5, link_candidates=links, link_weight=0.5)
        self.assertEqual(keys(out), ["A", "B", "L1", "L2", "G1", "G2"])
        by_key = {c["fusion_doc_key"]: c for c in out}
        self.assertEqual(by_key["L1"]["fusion_sources"], ["links", "graph"])
        self.assertEqual(by_key["G1"]["fusion_sources"], ["graph"])
        self.assertEqual(by_key["L2"]["retrieval_method"], "link")

    def test_d_graph_weight_is_only_an_on_off_switch(self):
        vector = vector_list("A", "B", "C")
        graph = graph_list("G1", "C", "G2")
        self.assertEqual(fuse_candidates(vector, graph, 0.15), fuse_candidates(vector, graph, 0.5))
        off = fuse_candidates(vector, graph, 0.0)
        self.assertEqual(keys(off), ["A", "B", "C"])
        self.assertTrue(all(c["fusion_sources"] == ["vector"] for c in off))

    def test_e_links_join_whatever_the_gate_weight_is_and_link_weight_does_not_rank(self):
        vector = vector_list("A", "B")
        links = link_list("L1")
        self.assertEqual(graph_weight(classify_query(NO_CONCEPT_QUESTION)), 0.0)
        # fuse_candidates: graph off, links on
        out = fuse_candidates(vector, graph_list("G1"), 0.0, link_candidates=links, link_weight=0.15)
        self.assertEqual(keys(out), ["A", "B", "L1"])
        self.assertNotIn("G1", keys(out))
        # link_weight no longer changes the order
        self.assertEqual(fuse_candidates(vector, [], 0.0, link_candidates=links, link_weight=0.15),
                         fuse_candidates(vector, [], 0.0, link_candidates=links, link_weight=0.5))
        # end to end through the gate
        fused = fuse_and_select(vector, graph_list("G1"), NO_CONCEPT_QUESTION, top_k=10,
                                link_candidates=links, link_weight=0.15)
        got = [c["metadata"]["document_id"] for c in fused]
        self.assertIn("L1", got)
        self.assertNotIn("G1", got)

    def test_f_regression_graph_member_no_longer_passes_the_rank1_document(self):
        # weight 0.15, graph member at vector rank 11: under the old arithmetic it passed rank 1
        vector = vector_list(*[f"D{i:02d}" for i in range(1, 13)])
        out = fuse_candidates(vector, graph_list("D11"), 0.15)
        self.assertEqual(keys(out), [f"D{i:02d}" for i in range(1, 13)])
        # weight 0.5, graph rank 1 on the vector rank-3 document: old order was C, A, B
        vector = vector_list("A", "B", "C")
        out = fuse_candidates(vector, graph_list("C"), 0.5)
        self.assertEqual(keys(out), ["A", "B", "C"])

    def test_fusion_score_is_strictly_monotonic_with_the_order(self):
        out = fuse_candidates(vector_list("A", "B", "C"), graph_list("G1", "G2"), 0.5,
                              link_candidates=link_list("L1"), link_weight=0.5)
        scores = [c["fusion_score"] for c in out]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len(set(scores)), len(scores))   # no ties: later stages sort by fusion_score

    def test_contract_fields_dedup_and_non_mutation_unchanged(self):
        vector = [make("X", 0.9), dict(make("X", 0.8), record_id="X_chunk_001"), make("Y", 0.7)]
        graph = graph_list("Z")
        snap_v, snap_g = copy.deepcopy(vector), copy.deepcopy(graph)
        out = fuse_candidates(vector, graph, 0.5)
        self.assertEqual((vector, graph), (snap_v, snap_g))
        self.assertEqual(keys(out), ["X", "Y", "Z"])      # chunk-level dedup by document key still holds
        for c in out:
            for field in ("fusion_score", "fusion_sources", "fusion_doc_key"):
                self.assertIn(field, c)
        self.assertEqual(out[0]["record_id"], "X_chunk_000")   # highest-original-score vector chunk represents X


if __name__ == "__main__":
    unittest.main(verbosity=2)
