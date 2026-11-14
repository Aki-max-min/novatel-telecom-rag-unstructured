"""
Retrieval-only comparison (NO LLM): the 14 E14a document questions on the old combined index vs the clean (no SciFact) index.

    python -m combined_retrieval.compare_scifact_index

Settings are those of the E14 searcher (integration/rag/pipeline.py): all-MiniLM-L6-v2 query embedding -> FAISS top-10 ->
ms-marco-MiniLM-L-6-v2 CrossEncoder rerank of those 10 -> documents in CrossEncoder order (a document counts once, at its best
chunk). R@k = a gold document is within the top-k documents; MRR@10 = 1/rank of the first gold document within 10.
Gold = expected_document_ids of the 8 synthetic (Q*) and 6 TRAI (RW_*) questions in
data/experiments/benchmark_base_vs_rag/queryset.json (the E14a question set, unchanged).

Three variants:
  old        data/experiments/combined_retrieval/vectorstore, SciFact included (what E14a ran on)
  old+filter the same index with SciFact dropped at serving time (over-fetch so 10 real candidates remain)
  clean      data/experiments/combined_retrieval_clean/vectorstore (1,420 chunks)
Also reported per question: how many SciFact chunks the old index returns in its FAISS top-10.

Outputs: docs/SCIFACT_INDEX_COMPARISON.md and docs/scifact_index_comparison.json, labelled "re-computed in this task".
E14a files are read, never written.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import faiss
from sentence_transformers import CrossEncoder, SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from integration.corpus_labels import count_scifact, is_scifact  # noqa: E402

OLD = ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore"
CLEAN = ROOT / "data" / "experiments" / "combined_retrieval_clean" / "vectorstore"
QUERYSET = ROOT / "data" / "experiments" / "benchmark_base_vs_rag" / "queryset.json"
SYNTH_CHUNKS = ROOT / "data" / "processed" / "chunks"
FAISS_TOP_K = 10          # same as integration/rag/pipeline.py FAISS_TOP_K
KS = (1, 3, 5, 10)


class Variant:
    def __init__(self, name: str, directory: Path, exclude_scifact: bool, encoder, reranker):
        self.name, self.exclude = name, exclude_scifact
        self.index = faiss.read_index(str(directory / "faiss.index"))
        self.metadata = json.loads((directory / "chunk_metadata.json").read_text(encoding="utf-8"))
        self.n_sf = count_scifact(self.metadata)
        self.encoder, self.reranker = encoder, reranker

    def text(self, rec: dict) -> str:
        if rec.get("text"):
            return rec["text"]
        return json.loads((SYNTH_CHUNKS / f"{rec['chunk_id']}.json").read_text(encoding="utf-8")).get("text", "")

    def search(self, query: str) -> dict:
        qv = self.encoder.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype("float32")
        fetch = FAISS_TOP_K + (self.n_sf if self.exclude else 0)
        _, idx = self.index.search(qv, min(fetch, self.index.ntotal))
        cands = []
        for i in idx[0]:
            if i < 0:
                continue
            rec = self.metadata[int(i)]
            if self.exclude and is_scifact(rec):
                continue
            if len(cands) >= FAISS_TOP_K:
                break
            cands.append(rec)
        scores = self.reranker.predict([(query, self.text(r)) for r in cands])
        ranked = [r for _, r in sorted(zip(scores, cands), key=lambda t: -float(t[0]))]
        docs: list[str] = []
        for r in ranked:
            if r["document_id"] not in docs:
                docs.append(r["document_id"])
        return {"docs": docs, "n_scifact_in_top10": sum(1 for r in cands if is_scifact(r))}


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    out = {"n": n}
    for k in KS:
        out[f"R@{k}"] = round(sum(any(d in r["gold"] for d in r["docs"][:k]) for r in rows) / n, 4)
    mrr = 0.0
    for r in rows:
        for rank, d in enumerate(r["docs"][:10], 1):
            if d in r["gold"]:
                mrr += 1 / rank
                break
    out["MRR@10"] = round(mrr / n, 4)
    return out


def main() -> None:
    queries = [q for q in json.loads(QUERYSET.read_text(encoding="utf-8"))["queries"]
               if q["reference_evidence"]["kind"] == "document_ids"]
    assert len(queries) == 14, len(queries)
    encoder = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
    reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    variants = [Variant("old", OLD, False, encoder, reranker), Variant("old+filter", OLD, True, encoder, reranker),
                Variant("clean", CLEAN, False, encoder, reranker)]
    per_q = []
    for q in queries:
        gold = set(q["reference_evidence"]["expected_document_ids"])
        row = {"query_id": q["query_id"], "question": q["question"], "gold": sorted(gold)}
        for v in variants:
            res = v.search(q["question"])
            row[v.name] = {"docs": res["docs"], "n_scifact_in_top10": res["n_scifact_in_top10"]}
        per_q.append(row)

    table = {}
    for v in variants:
        rows = [{"gold": set(r["gold"]), "docs": r[v.name]["docs"], "config": v.name} for r in per_q]
        table[v.name] = {"all_14": metrics(rows),
                         "synthetic_8": metrics([x for x, r in zip(rows, per_q) if r["query_id"].startswith("Q")]),
                         "trai_6": metrics([x for x, r in zip(rows, per_q) if r["query_id"].startswith("RW")])}
    differing = [r["query_id"] for r in per_q
                 if not (r["old"]["docs"] == r["old+filter"]["docs"] == r["clean"]["docs"])]
    sf_in_top10 = {r["query_id"]: r["old"]["n_scifact_in_top10"] for r in per_q if r["old"]["n_scifact_in_top10"]}
    payload = {"label": "re-computed in this task (retrieval only, no LLM); not an E14a file", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
               "settings": "all-MiniLM-L6-v2 -> FAISS top-10 -> ms-marco-MiniLM-L-6-v2 CrossEncoder rerank of the 10; docs deduplicated by best chunk",
               "indexes": {"old": str(OLD.relative_to(ROOT)).replace("\\", "/"), "clean": str(CLEAN.relative_to(ROOT)).replace("\\", "/"),
                           "old_chunks": variants[0].index.ntotal, "clean_chunks": variants[2].index.ntotal},
               "metrics": table, "questions_where_ranked_documents_differ_between_variants": differing,
               "scifact_chunks_in_old_faiss_top10": sf_in_top10, "per_question": per_q}
    (ROOT / "docs" / "scifact_index_comparison.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def line(name, m):
        return f"| {name} | {m['n']} | {m['R@1']:.4f} | {m['R@3']:.4f} | {m['R@5']:.4f} | {m['R@10']:.4f} | {m['MRR@10']:.4f} |"
    md = ["# SciFact in the combined index: retrieval comparison", "",
          "**Re-computed in this task** (retrieval only, no LLM, no E14a file written). Question set: the 14 E14a document questions "
          "(8 synthetic Q*, 6 TRAI RW_*) with their E14a gold documents. Settings: " + payload["settings"] + ".", "",
          f"Indexes: old = `{payload['indexes']['old']}` ({payload['indexes']['old_chunks']} chunks, includes 125 SciFact chunks); "
          f"clean = `{payload['indexes']['clean']}` ({payload['indexes']['clean_chunks']} chunks).", "",
          "| variant | n | R@1 | R@3 | R@5 | R@10 | MRR@10 |", "|---|---|---|---|---|---|---|"]
    for name in ("old", "old+filter", "clean"):
        md.append(line(name + " (all 14)", table[name]["all_14"]))
    for name in ("old", "clean"):
        md.append(line(name + " (synthetic 8)", table[name]["synthetic_8"]))
        md.append(line(name + " (TRAI 6)", table[name]["trai_6"]))
    md += ["", f"SciFact chunks in the old index's FAISS top-10 (questions with at least one): {sf_in_top10 or 'none'}.",
           f"Questions whose ranked document list differs between old, old+filter and clean: {differing or 'none'}.",
           "", "Per-question lists are in `docs/scifact_index_comparison.json`."]
    (ROOT / "docs" / "SCIFACT_INDEX_COMPARISON.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
