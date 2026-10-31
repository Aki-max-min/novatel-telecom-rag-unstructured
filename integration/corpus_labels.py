"""
Corpus labels for chunk metadata -- the single place that decides which corpus a chunk belongs to.

Why this exists. The combined FAISS index (data/experiments/combined_retrieval/vectorstore, 1,545 chunks) and the older
data/vectorstore index (383 chunks) both contain 125 chunks (100 documents) of the BEIR SciFact benchmark, which the project
policy treats as an EXTERNAL benchmark that must not sit in the telecom corpus. The combined index tags them
`source_corpus: "synthetic"`, so "383 synthetic" really is 258 NovaTel + 125 SciFact. The index files are not rewritten;
chunks are re-labelled at load time with the functions below.

How a SciFact chunk is recognised. By the `document_id` prefix `SCIFACT_`. Verified on both index files: the set of chunks
with that prefix is identical to the sets selected by `source_authority == "BEIR SciFact"`, `category == "SCIFACT"`, a
`file_path` containing "scifact" and a `scifact` tag (125 chunks in each). The prefix is used because it is the identifier the
rest of the code base already relies on (ingestion/evaluate_scifact.py).

Labels
    corpus_label   "NovaTel Synthetic" | "TRAI" | "SciFact"          (human-readable, stored as metadata["corpus_label"])
    dataset_label  "novatel_synthetic" | "trai_public" | "scifact_external"   (the Common Result Schema `dataset` value)
For every non-SciFact chunk `dataset_label` is exactly what the code produced before this module existed.
"""

from __future__ import annotations

SCIFACT_ID_PREFIX = "SCIFACT_"

LABEL_NOVATEL = "NovaTel Synthetic"
LABEL_TRAI = "TRAI"
LABEL_SCIFACT = "SciFact"

DATASET_NOVATEL = "novatel_synthetic"
DATASET_TRAI = "trai_public"
DATASET_SCIFACT = "scifact_external"

CORPUS_LABEL_OF_DATASET = {DATASET_NOVATEL: LABEL_NOVATEL, DATASET_TRAI: LABEL_TRAI, DATASET_SCIFACT: LABEL_SCIFACT}


def is_scifact(record: dict) -> bool:
    return str(record.get("document_id", "")).startswith(SCIFACT_ID_PREFIX)


def dataset_label(record: dict) -> str:
    if is_scifact(record):
        return DATASET_SCIFACT
    # unchanged from the pre-existing rule for every other chunk
    return DATASET_NOVATEL if record.get("source_corpus") == "synthetic" else DATASET_TRAI


def corpus_label(record: dict) -> str:
    return CORPUS_LABEL_OF_DATASET[dataset_label(record)]


def count_scifact(metadata: list[dict]) -> int:
    return sum(1 for r in metadata if is_scifact(r))
