"""
Lightweight semantic layer for the E14 RAG pipeline. OFF by default (RagConfig.semantic_layer = False).

Plain steps, for a question when the layer is on (all semantic content comes from Person B's modules; nothing here defines
ontology content):

  1. Concept hint.   hybrid/query_gate.classify_query(question) -> concept_hint, a concept from the shared vocabulary of
                     ontology/ontology_schema.json (Person B's rule-based gate, word-boundary matching), and
                     hybrid/query_gate.graph_weight(...) -> 0.5 / 0.15 / 0.0.
  2. Term expansion. The FAISS query text becomes: original question + the concept name + the document-category names the
                     ontology crosswalk (knowledge_graph.concept_bridge.load_crosswalk) links to that concept. Only the
                     FAISS candidate search sees the expanded text; the CrossEncoder still scores the ORIGINAL question.
  3. Seeds.          The top GRAPH_SEEDS reranked documents (Person B's default, 5) are the expansion seeds.
  4. Graph list.     knowledge_graph.graph_augmented_retrieval.graph_expand(seeds, ...) returns up to GRAPH_CANDIDATES
                     (Person B's default, 20) documents that share a bridge concept (Service / Channel /
                     VerificationMethod / Tag) with the seeds. Resolvable RELATED_TO links ("see also" links between
                     documents) from knowledge_graph/output/graph.json add their documents after those.
  5. Pool + merge.   Chunks of graph documents that are not already candidates (at most `max_chunks_per_doc` each) join the
                     pool, are scored by the CrossEncoder against the original question, and the pool is merged with the
                     CrossEncoder ranking by weighted Reciprocal Rank Fusion (ranks only, never scores) at the gate's graph
                     weight. A weight of 0.0 means the graph does not touch that question.
The merge itself lives in UnstructuredSearcher._semantic_merge (integration/rag/pipeline.py).

Dangling links. Every RELATED_TO link whose endpoint is not an indexed document is skipped, counted and logged once
(`link_report`, logger "novatel.semantic_layer"). At the time of writing all 84 links in the built graph are dangling
(docs/GRAPH_DANGLING_LINKS.md), so step 4's RELATED_TO part currently adds nothing and the layer never raises because of them.

Not part of the layer: the SQL side, the structured KG, ColPali, routing, citation checks. Nothing is tuned: there is no
development set separate from the evaluation questions.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GRAPH_JSON = ROOT / "knowledge_graph" / "output" / "graph.json"
log = logging.getLogger("novatel.semantic_layer")


class SemanticLayer:
    def __init__(self, graph_path: Path = GRAPH_JSON, max_chunks_per_doc: int = 2, use_related_links: bool = True,
                 _parts: dict | None = None):
        """`_parts` is for tests: {"classify", "graph_weight", "crosswalk_rows", "graph_expand", "graph_index",
        "bridges", "seeds", "candidates", "related_edges"} replaces everything that is read from Person B's modules/files."""
        self.max_chunks_per_doc = max_chunks_per_doc
        self.use_related_links = use_related_links
        self._report_logged = False
        self.stats = {"related_links_total": 0, "related_links_dangling": 0, "related_neighbours_added": 0}

        if _parts is None:
            for p in (str(ROOT), str(ROOT / "hybrid")):
                if p not in sys.path:
                    sys.path.insert(0, p)
            from knowledge_graph.concept_bridge import load_crosswalk
            from knowledge_graph.graph_augmented_retrieval import (DEFAULT_BRIDGES, GRAPH_CANDIDATES, GRAPH_SEEDS,
                                                                    graph_expand, load_graph_index)
            from query_gate import classify_query, graph_weight

            _parts = {"classify": classify_query, "graph_weight": graph_weight,
                      "crosswalk_rows": load_crosswalk()["rows"], "graph_expand": graph_expand,
                      "graph_index": load_graph_index(graph_path),  # FileNotFoundError names the build command
                      "bridges": DEFAULT_BRIDGES, "seeds": GRAPH_SEEDS, "candidates": GRAPH_CANDIDATES,
                      "related_edges": _read_related_edges(graph_path)}

        self._classify = _parts["classify"]
        self._graph_weight = _parts["graph_weight"]
        self._graph_expand = _parts["graph_expand"]
        self.graph_index = _parts["graph_index"]
        self._bridges = _parts["bridges"]
        self.seed_documents = _parts["seeds"]            # Person B's GRAPH_SEEDS
        self.max_graph_documents = _parts["candidates"]  # Person B's GRAPH_CANDIDATES
        self.concept_categories: dict[str, list[str]] = defaultdict(list)
        for row in _parts["crosswalk_rows"]:
            concept, name = row.get("shared_domain_concept"), row.get("document_category_name")
            if concept and name and name not in self.concept_categories[concept]:
                self.concept_categories[concept].append(name)
        self._related_edges = list(_parts.get("related_edges", []))
        self.related: dict[str, list[str]] = defaultdict(list)  # undirected "see also" adjacency
        for a, b in self._related_edges:
            for x, y in ((a, b), (b, a)):
                if y not in self.related[x]:
                    self.related[x].append(y)

    # -- steps 1 + 2 --------------------------------------------------------------------------
    def analyse(self, question: str) -> dict:
        c = self._classify(question)
        concept = c.get("concept_hint")
        terms = [concept] + self.concept_categories.get(concept, []) if concept else []
        return {"concept": concept, "terms": terms, "classification": c, "graph_weight": self._graph_weight(c)}

    def normalise_query(self, question: str) -> tuple[str, dict]:
        info = self.analyse(question)
        if not info["terms"]:
            return question, info
        return question + " " + ". ".join(info["terms"]) + ".", info

    # -- step 4 ---------------------------------------------------------------------------------
    def link_report(self, known_documents: set[str]) -> dict:
        """Counts RELATED_TO links whose two endpoints are both indexed documents; logs the dangling count once."""
        total = len(self._related_edges)
        resolvable = sum(1 for a, b in self._related_edges if a in known_documents and b in known_documents)
        self.stats.update(related_links_total=total, related_links_dangling=total - resolvable)
        if not self._report_logged:
            self._report_logged = True
            log.warning("semantic layer: %d of %d RELATED_TO links are dangling (an endpoint is not an indexed document) "
                        "and are skipped", total - resolvable, total)
        return {"total": total, "resolvable": resolvable, "dangling": total - resolvable}

    def neighbours(self, seed_documents: list[str], known_documents: set[str]) -> list[str]:
        """Person B's graph list first (best first; a seed that neighbours another seed stays in it, as in
        graph_augmented_retrieval.graph_enhanced_search), then resolvable RELATED_TO neighbours. Documents with no chunk in
        the index are dropped. Never raises because of dangling links."""
        self.link_report(known_documents)
        if not seed_documents:
            return []
        rows = self._graph_expand(seed_documents, self.graph_index, bridges=self._bridges, limit=self.max_graph_documents)
        out = [r["document_id"] for r in rows if r["document_id"] in known_documents]
        if self.use_related_links:
            for seed in seed_documents:
                for doc in self.related.get(seed, []):
                    if doc in known_documents and doc not in out:
                        out.append(doc)
                        self.stats["related_neighbours_added"] += 1
        return out

    @staticmethod
    def description() -> str:
        return ("Ontology term normalisation (concept hint from the shared ontology vocabulary appends the canonical "
                "concept and linked document-category names to the FAISS query) plus one-hop expansion over the document "
                "graph's shared-concept bridges and resolvable RELATED_TO links, merged with the CrossEncoder ranking by "
                "rank-based weighted RRF at the query gate's graph weight; the SQL side is unchanged.")


def _read_related_edges(graph_path: Path) -> list[tuple[str, str]]:
    payload = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    key_of = {n["id"]: n["key"] for n in payload["nodes"]}
    return [(key_of[e["source"]], key_of[e["target"]]) for e in payload["edges"] if e["type"] == "RELATED_TO"]
