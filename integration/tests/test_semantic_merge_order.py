"""UnstructuredSearcher._semantic_merge: graph neighbours may JOIN the candidate pool; the final order is the CrossEncoder score alone.

Written BEFORE the fix (Person B's report, 2026-11-11): the old merge added a weighted-RRF bonus graph_weight / (RRF_K + graph_rank) on top of
nearly flat base scores 1 / (RRF_K + rank), so any chunk of a graph-list document passed the CrossEncoder's best chunk from rank 11 (weight
0.15) or rank 61 (weight 0.5) whatever its CrossEncoder score. These tests pin the intended behaviour with a fake reranker; no network, no index.
"""

from __future__ import annotations

from integration.rag.pipeline import UnstructuredSearcher

CE = {"d1": 0.90, "d2": 0.80, "d3": 0.70, "d4": 0.60, "d5": 0.50, "n1": 0.65, "n2": 0.95, "n3": 0.10}   # CrossEncoder score per chunk text


class FakeReranker:
    def predict(self, pairs):
        return [CE[text] for _query, text in pairs]


class FakeLayer:
    """Only what _semantic_merge reads: seed_documents, max_chunks_per_doc, neighbours()."""

    def __init__(self, neighbour_docs):
        self.seed_documents = 5
        self.max_chunks_per_doc = 2
        self.neighbour_docs = list(neighbour_docs)
        self.seen_seeds = None

    def neighbours(self, seed_documents, known_documents):
        self.seen_seeds = list(seed_documents)
        return [d for d in self.neighbour_docs if d in known_documents]


def _record(doc, text):
    return {"document_id": doc, "chunk_id": f"{doc}_chunk_000", "text": text, "title": doc, "category": "", "department": "",
            "customer_scope": "", "related_ids": [], "tags": [], "source_corpus": "synthetic"}


def _searcher():
    s = UnstructuredSearcher.__new__(UnstructuredSearcher)          # no index / models: we only exercise _semantic_merge
    s.exclude_scifact = False
    s._text_cache = {}
    s.reranker = FakeReranker()
    s.metadata = [_record(d, t) for d, t in (("D1", "d1"), ("D2", "d2"), ("D3", "d3"), ("D4", "d4"), ("D5", "d5"), ("N1", "n1"), ("N2", "n2"), ("N3", "n3"))]
    return s


def _pool():
    """The FAISS + CrossEncoder candidates exactly as search() hands them over: sorted by hybrid_score, best first."""
    out = []
    for doc, text in (("D1", "d1"), ("D2", "d2"), ("D3", "d3"), ("D4", "d4"), ("D5", "d5")):
        c = dict(_record(doc, text))
        c.update(faiss_score=0.5, crossencoder_score=CE[text], hybrid_score=CE[text], corpus_label="novatel", _dataset="novatel_synthetic")
        out.append(c)
    return out


def _docs(pool):
    return [c["document_id"] for c in pool]


def _merge(neighbours, weight):
    s = _searcher()
    layer = FakeLayer(neighbours)
    return s._semantic_merge("q", _pool(), layer, {"graph_weight": weight, "concept": "X"}), layer


def test_1_original_candidates_keep_their_relative_order_with_the_layer_on():
    off = _docs(_pool())
    for neighbours in (["D3", "N1"], ["D5"], ["N2", "D2", "D4"], ["D1", "D2", "D3", "D4", "D5"]):
        for weight in (0.15, 0.5):
            merged, _ = _merge(neighbours, weight)
            assert [d for d in _docs(merged) if d in off] == off, f"neighbours={neighbours} weight={weight}: {_docs(merged)}"


def test_2_an_added_chunk_ranks_above_an_existing_chunk_only_if_its_crossencoder_score_is_higher():
    merged, _ = _merge(["N1", "N2", "N3"], 0.5)
    docs = _docs(merged)
    assert docs == ["N2", "D1", "D2", "D3", "N1", "D4", "D5", "N3"], docs      # N2 .95 > D1 .90; D3 .70 > N1 .65 > D4 .60; N3 .10 last
    scores = [c["hybrid_score"] for c in merged]
    assert scores == sorted(scores, reverse=True)
    assert all(c.get("semantic_added") is True for c in merged if c["document_id"].startswith("N"))
    assert not any(c.get("semantic_added") for c in merged if c["document_id"].startswith("D"))


def test_3_graph_weight_015_and_05_give_the_same_order():
    for neighbours in (["N1", "N2"], ["D3", "N1"], ["D5", "N3"]):
        a, _ = _merge(neighbours, 0.15)
        b, _ = _merge(neighbours, 0.5)
        assert [c["chunk_id"] for c in a] == [c["chunk_id"] for c in b], neighbours
        assert a[0]["semantic"]["graph_weight"] == 0.15 and b[0]["semantic"]["graph_weight"] == 0.5    # the trace still records the weight


def test_4_regression_old_arithmetic_a_graph_member_at_crossencoder_rank_5_must_not_pass_rank_1():
    # Old merge: D5 (rank 5) in the graph list got 1/(60+5) + 0.15/(60+1) = 0.01784 > D1's 1/(60+1) = 0.01639 and moved to rank 1.
    for weight in (0.15, 0.5):
        merged, _ = _merge(["D5"], weight)
        assert _docs(merged) == ["D1", "D2", "D3", "D4", "D5"], _docs(merged)


def test_graph_weight_zero_adds_nothing_and_keeps_the_order():
    merged, layer = _merge(["N1", "N2"], 0.0)
    assert _docs(merged) == ["D1", "D2", "D3", "D4", "D5"]
    assert not any(c.get("semantic_added") for c in merged)
    assert layer.seen_seeds == ["D1", "D2", "D3", "D4", "D5"]


def test_trace_fields_are_kept_on_every_chunk():
    merged, _ = _merge(["N1"], 0.15)
    for c in merged:
        assert c["semantic"]["concept"] == "X" and c["semantic"]["seeds"] == ["D1", "D2", "D3", "D4", "D5"]
        assert c["semantic"]["neighbour_docs"] == ["N1"] and c["semantic"]["graph_weight"] == 0.15
        assert c["semantic"]["added_by_graph"] == (c["document_id"] == "N1")


def test_ties_are_broken_by_chunk_id_and_the_order_is_stable():
    s = _searcher()
    s.metadata.append(_record("N0", "n0"))
    CE["n0"] = CE["d3"]                       # exact tie with D3
    try:
        merged = s._semantic_merge("q", _pool(), FakeLayer(["N0"]), {"graph_weight": 0.5})
        docs = _docs(merged)
        assert docs.index("D3") < docs.index("N0")        # "D3_chunk_000" < "N0_chunk_000"
        assert docs[:2] == ["D1", "D2"] and docs[-2:] == ["D4", "D5"]
    finally:
        CE.pop("n0")
