"""
Retrieval backends. Both emit the extended Common Evidence Schema
(integration/qa/evidence.py) and are called independently by the system.

StructuredBackend
    Wraps the EXISTING structured/retriever.py::StructuredRetriever (SQL via
    exact lookup / exact filter / aggregate, rule-based query parser). A thin
    adapter only: structured/ is not modified. A fresh retriever (= fresh
    sqlite connection) is created per call because sqlite3 connections are bound
    to the creating thread and Streamlit runs scripts on different threads.
    Exact structured retrieval is NEVER replaced by vector search.

UnstructuredBackend
    The combined 1,545-chunk FAISS index (383 NovaTel synthetic + 1,162 TRAI
    public chunks, from E9), MiniLM query encoder, CrossEncoder rerank. Optional,
    switchable components (all off by default so ablations stay clean):
      use_doc_graph : Person B's document knowledge graph. Seed documents ->
                      graph_expand() -> neighbour documents added to the candidate
                      pool; its rank list enters weighted RRF with weight =
                      hybrid.query_gate.graph_weight (Person B's validated gate:
                      0.0 / 0.15 / 0.5). Requires knowledge_graph/output/graph.json
                      (regenerable: python -m knowledge_graph.graph_builder).
      use_ontology  : the shared concept vocabulary (ontology/ontology_schema.json
                      crosswalk). query_gate.classify_query -> concept_hint ->
                      the document-category codes the crosswalk links to that
                      concept -> an "ontology" rank list (same RRF mechanism).
      use_colpali   : page-image retrieval; availability-gated (needs the GPU the
                      Ollama generator also uses) -- see ColPaliAdapter.
    Fusion across these lists is RANK-BASED weighted RRF only. FAISS cosine,
    CrossEncoder logits and graph overlap counts are never added together.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

from integration.qa.config import QAConfig
from integration.qa.evidence import (PUBLIC_DATASET, SYNTHETIC_DATASET, structured_evidence,
                                     unstructured_evidence)
from integration.qa.page_map import get_page_info

ROOT = Path(__file__).resolve().parents[2]
STRUCTURED_DIR = ROOT / "structured"
COMBINED_DIR = ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore"
SYNTHETIC_CHUNK_DIR = ROOT / "data" / "processed" / "chunks"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CUSTOMER_ID_RE = re.compile(r"customer\s*(?:id|no\.?|number)?\s*#?\s*(\d{4,})", re.I)
ONTOLOGY_DEPTH = 50  # how deep into the FAISS list the ontology filter looks


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ===========================================================================
# Structured
# ===========================================================================
class StructuredBackend:
    """Thin adapter over structured/retriever.py (unchanged)."""

    def __init__(self):
        if str(STRUCTURED_DIR) not in sys.path:
            sys.path.insert(0, str(STRUCTURED_DIR))

    def parse(self, sub_query: str) -> dict:
        from query_parser import parse_query
        return parse_query(sub_query)

    def can_execute(self, sub_query: str) -> tuple[bool, dict]:
        parsed = self.parse(sub_query)
        ok = parsed.get("table") is not None and parsed.get("method") not in (None, "exact_filter_unresolved")
        return ok, parsed

    def search(self, sub_query: str, cfg: QAConfig, origin: str = "original") -> tuple[list[dict], dict]:
        from retriever import StructuredRetriever
        from schema import get_schema

        start = time.perf_counter()
        retriever = StructuredRetriever()
        profile_fallback = None
        try:
            res = retriever.search(sub_query, top_k=cfg.top_k_structured)
            # Person B's parser sends every KYC phrasing to kyc_records, which holds only submitted-document rows;
            # the customer's KYC *status* lives in customer_master. If a customer-scoped lookup comes back empty,
            # retry ONCE with the profile lookup (thin adapter behaviour; structured/ is untouched) and say so.
            cust = CUSTOMER_ID_RE.search(sub_query)
            first_table = (res.get("parsed_query") or {}).get("table")
            if not res.get("results") and cust and first_table not in (None, "customer_master"):
                profile_query = f"What is the account status of customer {cust.group(1)}?"
                retry = retriever.search(profile_query, top_k=cfg.top_k_structured)
                if retry.get("results"):
                    profile_fallback = {"from_table": first_table, "to_table": "customer_master", "query": profile_query}
                    res, sub_query = retry, profile_query
        finally:
            retriever.close()
        parsed = res.get("parsed_query") or {}
        table = parsed.get("table")
        pk = (get_schema(table) or {}).get("primary_key") if table else None
        evidence = [structured_evidence(r, parsed=parsed, sub_query=sub_query, origin=origin, primary_key=pk)
                    for r in res.get("results", [])]
        diag = {"sub_query": sub_query, "parsed_query": parsed, "n_results": len(evidence),
                "resolved": bool(table) and parsed.get("method") not in (None, "exact_filter_unresolved"),
                "note": res.get("note"), "profile_fallback": profile_fallback, "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
        return evidence, diag


# ===========================================================================
# Unstructured
# ===========================================================================
class UnstructuredBackend:
    def __init__(self):
        import faiss
        from sentence_transformers import CrossEncoder, SentenceTransformer

        self.index = faiss.read_index(str(COMBINED_DIR / "faiss.index"))
        with open(COMBINED_DIR / "chunk_metadata.json", "r", encoding="utf-8") as f:
            self.metadata = json.load(f)
        self.encoder = SentenceTransformer(EMBEDDING_MODEL, local_files_only=True)
        self.reranker = CrossEncoder(RERANKER_MODEL)
        self._text_cache: dict[str, str] = {}

        self.pos_by_chunk = {m["chunk_id"]: i for i, m in enumerate(self.metadata)}
        self.chunks_by_doc: dict[str, list[int]] = {}
        for i, m in enumerate(self.metadata):
            self.chunks_by_doc.setdefault(m["document_id"], []).append(i)

        self._graph_index = None
        self._concept_categories = None

    # -- text / labels -----------------------------------------------------
    def _text(self, record: dict) -> str:
        if record.get("text"):
            return record["text"]
        cid = record["chunk_id"]
        if cid not in self._text_cache:
            path = SYNTHETIC_CHUNK_DIR / f"{cid}.json"
            self._text_cache[cid] = json.load(open(path, "r", encoding="utf-8")).get("text", "")
        return self._text_cache[cid]

    @staticmethod
    def _dataset(record: dict) -> str:
        return SYNTHETIC_DATASET if record.get("source_corpus") == "synthetic" else PUBLIC_DATASET

    # -- optional components ----------------------------------------------
    def _load_graph(self):
        if self._graph_index is None:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from knowledge_graph.graph_augmented_retrieval import load_graph_index
            self._graph_index = load_graph_index()
        return self._graph_index

    def _concept_to_categories(self) -> dict:
        if self._concept_categories is None:
            from knowledge_graph.concept_bridge import load_crosswalk
            mapping: dict[str, set] = {}
            for row in load_crosswalk()["rows"]:
                if row.get("shared_domain_concept") and row.get("document_category_code"):
                    mapping.setdefault(row["shared_domain_concept"], set()).add(row["document_category_code"])
            self._concept_categories = mapping
        return self._concept_categories

    @staticmethod
    def _gate(question: str) -> dict:
        hybrid_dir = ROOT / "hybrid"
        for p in (str(ROOT), str(hybrid_dir)):
            if p not in sys.path:
                sys.path.insert(0, p)
        from query_gate import classify_query, graph_weight
        c = classify_query(question)
        return {"classification": c, "graph_weight": graph_weight(c)}

    def graph_available(self) -> tuple[bool, str]:
        path = ROOT / "knowledge_graph" / "output" / "graph.json"
        if not path.exists():
            return False, "knowledge_graph/output/graph.json missing (run: python -m knowledge_graph.graph_builder)"
        return True, ""

    # -- main --------------------------------------------------------------
    def search(self, sub_query: str, cfg: QAConfig, origin: str = "original") -> tuple[list[dict], dict]:
        start = time.perf_counter()
        qvec = self.encoder.encode([sub_query], convert_to_numpy=True, normalize_embeddings=True).astype("float32")
        depth = max(cfg.faiss_depth, ONTOLOGY_DEPTH if cfg.use_ontology else 0)
        scores, indices = self.index.search(qvec, min(depth, self.index.ntotal))

        faiss_rank = {}   # chunk position -> (rank, score)
        for rank, (sc, pos) in enumerate(zip(scores[0], indices[0]), start=1):
            if pos >= 0:
                faiss_rank[int(pos)] = (rank, float(sc))
        pool = [pos for pos, (r, _) in sorted(faiss_rank.items(), key=lambda kv: kv[1][0]) if r <= cfg.faiss_depth]

        extra_lists: dict[str, list[int]] = {}
        relationships: dict[int, list] = {}
        concepts: list = []
        weights: dict[str, float] = {}
        diag: dict = {"components": []}

        # ---- + document graph -------------------------------------------
        if cfg.use_doc_graph:
            ok, why = self.graph_available()
            if not ok:
                diag["components"].append({"doc_graph": f"unavailable: {why}"})
            else:
                from knowledge_graph.graph_augmented_retrieval import DEFAULT_BRIDGES, graph_expand
                gi = self._load_graph()
                seed_docs = []
                for pos in pool[:5]:
                    d = self.metadata[pos]["document_id"]
                    if d not in seed_docs and self.metadata[pos].get("source_corpus") == "synthetic":
                        seed_docs.append(d)
                expanded = graph_expand(seed_docs, gi, bridges=DEFAULT_BRIDGES, limit=20)
                gate = self._gate(sub_query)
                weights["graph"] = cfg.graph_weight if cfg.graph_weight is not None else gate["graph_weight"]
                graph_positions = []
                for row in expanded:
                    doc = row["document_id"]
                    if doc not in self.chunks_by_doc:
                        continue
                    pos = sorted(self.chunks_by_doc[doc])[0]
                    graph_positions.append(pos)
                    relationships.setdefault(pos, []).extend(row["shared_concepts"])
                    if pos not in pool and len(pool) < cfg.faiss_depth + 10:
                        pool.append(pos)
                extra_lists["graph"] = graph_positions
                diag["components"].append({"doc_graph": {"seeds": seed_docs, "added": len(graph_positions),
                                                          "weight": weights["graph"]}})

        # ---- + ontology ---------------------------------------------------
        if cfg.use_ontology:
            gate = self._gate(sub_query)
            hint = gate["classification"].get("concept_hint")
            codes = self._concept_to_categories().get(hint, set()) if hint else set()
            weights["ontology"] = cfg.ontology_weight if codes else 0.0
            onto_positions = []
            if codes:
                concepts = [hint]
                for pos, (r, _) in sorted(faiss_rank.items(), key=lambda kv: kv[1][0]):
                    if self.metadata[pos].get("category") in codes:
                        onto_positions.append(pos)
                        if pos not in pool and len(pool) < cfg.faiss_depth + 10:
                            pool.append(pos)
                    if len(onto_positions) >= 10:
                        break
            extra_lists["ontology"] = onto_positions
            diag["components"].append({"ontology": {"concept_hint": hint, "category_codes": sorted(codes),
                                                     "candidates": len(onto_positions), "weight": weights["ontology"]}})

        # ---- CrossEncoder over the pool ---------------------------------
        texts = {pos: self._text(self.metadata[pos]) for pos in pool}
        ce = self.reranker.predict([(sub_query, texts[pos]) for pos in pool]) if pool else []
        ce_score = {pos: float(s) for pos, s in zip(pool, ce)}
        ce_order = sorted(pool, key=lambda p: ce_score[p], reverse=True)

        # ---- weighted RRF across rank lists (ranks only, never scores) --
        if extra_lists:
            fused: dict[int, float] = {}
            lists = [("ce", ce_order, 1.0)] + [(n, l, weights.get(n, 0.0)) for n, l in extra_lists.items()]
            for _name, order, w in lists:
                for rank, pos in enumerate(order, start=1):
                    fused[pos] = fused.get(pos, 0.0) + w / (cfg.rrf_k + rank)
            final = sorted(pool, key=lambda p: (-fused[p], -ce_score[p]))
        else:
            final = ce_order

        final = final[:cfg.top_k_unstructured]

        evidence = []
        for pos in final:
            rec = self.metadata[pos]
            dataset = self._dataset(rec)
            page = get_page_info(rec["chunk_id"]) if dataset == PUBLIC_DATASET else None
            rank, fscore = faiss_rank.get(pos, (None, None))
            ev = unstructured_evidence(
                document_id=rec["document_id"], chunk_id=rec["chunk_id"], dataset=dataset,
                category=rec.get("category", ""), content=texts[pos], title=rec.get("title", ""),
                retrieval_method="faiss+crossencoder" + ("+" + "+".join(extra_lists) if extra_lists else ""),
                raw_scores={"faiss_cosine": fscore, "faiss_rank": rank, "crossencoder_logit": ce_score[pos],
                            "crossencoder_sigmoid": round(sigmoid(ce_score[pos]), 6)},
                score=ce_score[pos], sub_query=sub_query, origin=origin,
                page_number=page["page"] if page else None,
                source_authority=rec.get("source_authority"), document_type=rec.get("document_type"),
                ontology_concepts=concepts or None, relationships=sorted(set(relationships.get(pos, []))) or None,
            )
            if page:
                ev["metadata"]["page_range"] = page["pages"]
                ev["metadata"]["page_overlap"] = page["overlap"]
            evidence.append(ev)

        top_ce = max(ce_score.values()) if ce_score else None
        diag.update({
            "sub_query": sub_query, "n_results": len(evidence), "pool_size": len(pool),
            "top_crossencoder_logit": top_ce,
            "top_crossencoder_sigmoid": round(sigmoid(top_ce), 6) if top_ce is not None else None,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        })
        return evidence, diag


class ColPaliAdapter:
    """Availability-gated page-image retrieval (public PDFs only).

    STATUS: wired as a switch, availability-checked, NOT exercised in the live path.
    ColPali (vidore/colpali-v1.3-hf, fp16) needs most of the 8 GB GPU and re-scores 878
    page tensors per query; the Ollama generator holds the same GPU. `available()`
    therefore requires enough FREE VRAM. See docs for the measured status.
    """

    MIN_FREE_GIB = 7.0

    def available(self) -> tuple[bool, str]:
        emb = ROOT / "data" / "experiments" / "public_pdfs" / "colpali" / "embeddings"
        if not emb.exists() or not any(emb.rglob("*.pt")):
            return False, "ColPali page embeddings not present on disk (regenerable, git-ignored)"
        try:
            import torch
            if not torch.cuda.is_available():
                return False, "no CUDA GPU for ColPali"
            free, _total = torch.cuda.mem_get_info()
            if free / 2**30 < self.MIN_FREE_GIB:
                return False, f"only {free / 2**30:.1f} GiB GPU memory free (< {self.MIN_FREE_GIB}; the Ollama model holds the GPU)"
        except Exception as exc:  # noqa: BLE001
            return False, f"cannot probe GPU: {exc}"
        return True, ""
