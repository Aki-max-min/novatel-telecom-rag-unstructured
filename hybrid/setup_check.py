"""
Setup check after cloning:  python -m hybrid.setup_check

Prints OK or MISSING for each generated asset the hybrid layer needs, with the command that fixes it.
It never builds anything itself and makes no network call. Exit code 0 when everything is present, 1 otherwise.

  structured DB   data/processed/structured/novatel_structured.db
  graph.json      knowledge_graph/output/graph.json   (generated, not tracked in git)
  FAISS index     data/vectorstore/faiss.index + chunk_metadata.json
  model files     the embedding model and the CrossEncoder in the local Hugging Face cache
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EMBEDDING_MODEL_DIR = "models--sentence-transformers--all-MiniLM-L6-v2"
CROSSENCODER_MODEL_DIR = "models--cross-encoder--ms-marco-MiniLM-L-6-v2"
MODEL_FIX = ("python -c \"from sentence_transformers import SentenceTransformer, CrossEncoder; "
             "SentenceTransformer('all-MiniLM-L6-v2'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')\" "
             "(downloads once; needs internet)")


def hf_cache_dir() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return home / "hub"


def _model_cached(cache: Path, folder: str) -> bool:
    snapshots = cache / folder / "snapshots"
    return snapshots.exists() and any(snapshots.iterdir())


def check(root: Path = REPO_ROOT, hf_cache: Path = None):
    """[(name, ok, detail, fix_command)] for every asset."""
    root = Path(root)
    cache = hf_cache if hf_cache is not None else hf_cache_dir()
    rows = []

    db = root / "data" / "processed" / "structured" / "novatel_structured.db"
    rows.append(("structured DB", db.exists(), str(db), "python structured/build_database.py"))

    graph = root / "knowledge_graph" / "output" / "graph.json"
    rows.append(("graph.json", graph.exists(), str(graph), "python -m knowledge_graph.graph_builder"))

    index = root / "data" / "vectorstore" / "faiss.index"
    meta = root / "data" / "vectorstore" / "chunk_metadata.json"
    rows.append(("FAISS index", index.exists() and meta.exists(), f"{index} + {meta.name}",
                 "python -m ingestion.chunk_documents && python -m ingestion.embed_chunks "
                 "&& python -m ingestion.build_faiss_index"))

    emb = _model_cached(cache, EMBEDDING_MODEL_DIR)
    ce = _model_cached(cache, CROSSENCODER_MODEL_DIR)
    missing = [name for name, ok in (("all-MiniLM-L6-v2", emb), ("cross-encoder/ms-marco-MiniLM-L-6-v2", ce)) if not ok]
    rows.append(("model files", emb and ce,
                 f"{cache} ({'both cached' if not missing else 'missing: ' + ', '.join(missing)})", MODEL_FIX))
    return rows


def main(argv=None) -> int:
    rows = check()
    print("===== HYBRID SETUP CHECK =====")
    for name, ok, detail, fix in rows:
        print(f"{'OK     ' if ok else 'MISSING'}  {name:<14} {detail}")
        if not ok:
            print(f"         fix: {fix}")
    all_ok = all(ok for _, ok, _, _ in rows)
    print("all assets present" if all_ok else "some assets are missing - run the fix commands above")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
