"""
Build a CLEAN combined index (no SciFact) NEXT TO the existing one; the existing files are never touched.

    python -m combined_retrieval.build_clean_index

Source : data/experiments/combined_retrieval/vectorstore/{faiss.index, chunk_metadata.json}   (1,545 chunks)
Target : data/experiments/combined_retrieval_clean/vectorstore/{faiss.index, chunk_metadata.json, index_manifest.json}
Result : 1,420 chunks = 258 NovaTel synthetic + 1,162 TRAI public (the 125 SciFact chunks, 100 documents, are left out).

The source index is an IndexFlatIP, which stores its vectors exactly, so the kept vectors are copied with
`reconstruct_n` (no re-embedding, identical embeddings, same all-MiniLM-L6-v2 model, same order). Each metadata record gains a
`corpus_label` field. The script refuses to run if the target files already exist, and checks the result before writing the
manifest (path, chunk count, composition, sha256 of both files, source hashes).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import faiss
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from integration.corpus_labels import corpus_label, is_scifact  # noqa: E402

SRC = ROOT / "data" / "experiments" / "combined_retrieval" / "vectorstore"
DST = ROOT / "data" / "experiments" / "combined_retrieval_clean" / "vectorstore"
EXPECTED = {"NovaTel Synthetic": 258, "TRAI": 1162, "SciFact": 125}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    targets = [DST / "faiss.index", DST / "chunk_metadata.json", DST / "index_manifest.json"]
    existing = [p for p in targets if p.exists()]
    if existing:
        raise SystemExit(f"refusing to overwrite: {[str(p) for p in existing]}")

    index = faiss.read_index(str(SRC / "faiss.index"))
    if not isinstance(index, faiss.IndexFlatIP):
        raise SystemExit(f"expected IndexFlatIP (exact vectors), got {type(index).__name__}")
    metadata = json.loads((SRC / "chunk_metadata.json").read_text(encoding="utf-8"))
    if len(metadata) != index.ntotal:
        raise SystemExit("metadata / index length mismatch")

    source_composition: dict[str, int] = {}
    for rec in metadata:
        source_composition[corpus_label(rec)] = source_composition.get(corpus_label(rec), 0) + 1
    if source_composition != EXPECTED:
        raise SystemExit(f"unexpected source composition {source_composition}, expected {EXPECTED}")

    keep = [i for i, rec in enumerate(metadata) if not is_scifact(rec)]
    vectors = index.reconstruct_n(0, index.ntotal)[keep]
    clean = faiss.IndexFlatIP(index.d)
    clean.add(np.ascontiguousarray(vectors, dtype="float32"))
    clean_metadata = [{**metadata[i], "corpus_label": corpus_label(metadata[i])} for i in keep]

    # verification before anything is written
    assert clean.ntotal == len(clean_metadata) == len(metadata) - EXPECTED["SciFact"] == 1420
    assert not any(is_scifact(r) for r in clean_metadata)
    assert np.allclose(clean.reconstruct(7), index.reconstruct(keep[7]))

    DST.mkdir(parents=True, exist_ok=True)
    faiss.write_index(clean, str(DST / "faiss.index"))
    (DST / "chunk_metadata.json").write_text(json.dumps(clean_metadata, ensure_ascii=False), encoding="utf-8")
    composition: dict[str, int] = {}
    for rec in clean_metadata:
        composition[rec["corpus_label"]] = composition.get(rec["corpus_label"], 0) + 1
    manifest = {
        "description": "Combined index without SciFact, built beside the original by combined_retrieval/build_clean_index.py",
        "path": str(DST.relative_to(ROOT)).replace("\\", "/"),
        "chunks": clean.ntotal, "dimension": clean.d, "index_type": type(clean).__name__, "composition": composition,
        "embedding_model": "all-MiniLM-L6-v2 (vectors copied exactly from the source index, not recomputed)",
        "sha256": {"faiss.index": sha256(DST / "faiss.index"), "chunk_metadata.json": sha256(DST / "chunk_metadata.json")},
        "source": {"path": str(SRC.relative_to(ROOT)).replace("\\", "/"), "chunks": index.ntotal,
                   "composition": source_composition,
                   "sha256": {"faiss.index": sha256(SRC / "faiss.index"), "chunk_metadata.json": sha256(SRC / "chunk_metadata.json")}},
        "removed": {"chunks": EXPECTED["SciFact"], "rule": "document_id starts with 'SCIFACT_'"},
    }
    (DST / "index_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("path", "chunks", "composition", "sha256")}, indent=2))


if __name__ == "__main__":
    main()
