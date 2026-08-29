import json
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer, CrossEncoder


# ============================================================
# PATHS
# ============================================================

BENCHMARK_PATH = Path(
    "ingestion/retrieval_benchmark.json"
)

INDEX_PATH = Path(
    "data/vectorstore/faiss.index"
)

METADATA_PATH = Path(
    "data/vectorstore/chunk_metadata.json"
)

CHUNK_DIR = Path(
    "data/processed/chunks"
)

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Lightweight cross-encoder for second-stage reranking
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ============================================================
# LOAD CHUNK TEXT
# ============================================================

def load_chunk_text(chunk_id):
    chunk_path = CHUNK_DIR / f"{chunk_id}.json"

    if not chunk_path.exists():
        raise FileNotFoundError(
            f"Chunk file not found: {chunk_path}"
        )

    with open(
        chunk_path,
        "r",
        encoding="utf-8"
    ) as f:
        chunk = json.load(f)

    text = chunk.get("text", "")

    if not text.strip():
        raise ValueError(
            f"Empty text in chunk: {chunk_path}"
        )

    return text


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("NOVATEL RERANKING EXPERIMENT")
    print("=" * 80)

    # --------------------------------------------------------
    # Load benchmark
    # --------------------------------------------------------

    with open(
        BENCHMARK_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        benchmark = json.load(f)

    # --------------------------------------------------------
    # Load metadata
    # --------------------------------------------------------

    with open(
        METADATA_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        metadata = json.load(f)

    # --------------------------------------------------------
    # Load FAISS
    # --------------------------------------------------------

    index = faiss.read_index(
        str(INDEX_PATH)
    )

    # --------------------------------------------------------
    # Load embedding model
    # --------------------------------------------------------

    print("\nLoading embedding model...")

    embedding_model = SentenceTransformer(
        EMBEDDING_MODEL_NAME,
        local_files_only=True
    )

    # --------------------------------------------------------
    # Load reranker
    # --------------------------------------------------------

    print("Loading reranker...")

    reranker = CrossEncoder(
        RERANKER_MODEL_NAME
    )

    # --------------------------------------------------------
    # Load chunk texts
    # --------------------------------------------------------

    print("Loading chunk text...")

    chunk_texts = {}

    for doc in metadata:

        chunk_id = doc["chunk_id"]

        chunk_texts[chunk_id] = (
            load_chunk_text(chunk_id)
        )

    print(
        f"Benchmark questions: {len(benchmark)}"
    )

    print(
        f"FAISS vectors: {index.ntotal}"
    )

    # ========================================================
    # METRICS
    # ========================================================

    top1_hits = 0
    top3_hits = 0
    top5_hits = 0

    precision_at_1_total = 0.0
    precision_at_3_total = 0.0
    precision_at_5_total = 0.0

    results = []

    # ========================================================
    # EVALUATE
    # ========================================================

    for item in benchmark:

        question = item["question"]

        expected_ids = set(
            item["expected_document_ids"]
        )

        # ----------------------------------------------------
        # Stage 1: FAISS candidate retrieval
        # ----------------------------------------------------

        query_embedding = embedding_model.encode(
            [question],
            convert_to_numpy=True,
            normalize_embeddings=True
        ).astype("float32")

        # Retrieve 10 candidates instead of 5
        scores, indices = index.search(
            query_embedding,
            10
        )

        candidates = []

        for score, idx in zip(
            scores[0],
            indices[0]
        ):

            doc = metadata[idx]

            chunk_id = doc["chunk_id"]

            text = chunk_texts.get(
                chunk_id,
                ""
            )

            candidates.append(
                {
                    "document_id":
                        doc["document_id"],

                    "chunk_id":
                        chunk_id,

                    "category":
                        doc["category"],

                    "title":
                        doc["title"],

                    "faiss_score":
                        float(score),

                    "text":
                        text
                }
            )

        # ----------------------------------------------------
        # Stage 2: CrossEncoder reranking
        # ----------------------------------------------------

        pairs = [
            (
                question,
                candidate["text"]
            )
            for candidate in candidates
        ]

        reranker_scores = reranker.predict(
            pairs
        )

        for candidate, reranker_score in zip(
            candidates,
            reranker_scores
        ):
            candidate["reranker_score"] = float(
                reranker_score
            )

        # Highest reranker score first
        reranked = sorted(
            candidates,
            key=lambda x: x["reranker_score"],
            reverse=True
        )

        # ----------------------------------------------------
        # Evaluate top 1 / 3 / 5
        # ----------------------------------------------------

        retrieved_ids = [
            x["document_id"]
            for x in reranked
        ]

        hit1 = any(
            doc_id in expected_ids
            for doc_id in retrieved_ids[:1]
        )

        hit3 = any(
            doc_id in expected_ids
            for doc_id in retrieved_ids[:3]
        )

        hit5 = any(
            doc_id in expected_ids
            for doc_id in retrieved_ids[:5]
        )

        if hit1:
            top1_hits += 1

        if hit3:
            top3_hits += 1

        if hit5:
            top5_hits += 1

        # ----------------------------------------------------
        # Precision
        # ----------------------------------------------------

        def precision_at_k(k):

            top_k = reranked[:k]

            if not top_k:
                return 0.0

            relevant = sum(
                1
                for doc in top_k
                if doc["document_id"]
                in expected_ids
            )

            return relevant / len(top_k)

        p1 = precision_at_k(1)
        p3 = precision_at_k(3)
        p5 = precision_at_k(5)

        precision_at_1_total += p1
        precision_at_3_total += p3
        precision_at_5_total += p5

        # ----------------------------------------------------
        # Save result
        # ----------------------------------------------------

        results.append(
            {
                "question_id":
                    item["question_id"],

                "category":
                    item["category"],

                "question":
                    question,

                "expected_document_ids":
                    list(expected_ids),

                "top5":
                    reranked[:5],

                "document_hit_top1":
                    hit1,

                "document_hit_top3":
                    hit3,

                "document_hit_top5":
                    hit5,

                "precision_at_1":
                    p1,

                "precision_at_3":
                    p3,

                "precision_at_5":
                    p5
            }
        )

    # ========================================================
    # AGGREGATE RESULTS
    # ========================================================

    total = len(benchmark)

    precision_at_1 = (
        precision_at_1_total / total
    )

    precision_at_3 = (
        precision_at_3_total / total
    )

    precision_at_5 = (
        precision_at_5_total / total
    )

    # ========================================================
    # PRINT RESULTS
    # ========================================================

    print()
    print("=" * 80)
    print("RERANKED RETRIEVAL RESULTS")
    print("=" * 80)

    print(
        f"Top-1: {top1_hits}/{total} "
        f"({top1_hits / total * 100:.2f}%)"
    )

    print(
        f"Top-3: {top3_hits}/{total} "
        f"({top3_hits / total * 100:.2f}%)"
    )

    print(
        f"Top-5: {top5_hits}/{total} "
        f"({top5_hits / total * 100:.2f}%)"
    )

    print()
    print("=" * 80)
    print("RERANKED PRECISION")
    print("=" * 80)

    print(
        f"Precision@1: "
        f"{precision_at_1 * 100:.2f}%"
    )

    print(
        f"Precision@3: "
        f"{precision_at_3 * 100:.2f}%"
    )

    print(
        f"Precision@5: "
        f"{precision_at_5 * 100:.2f}%"
    )

    # ========================================================
    # PER QUESTION
    # ========================================================

    print()
    print("=" * 80)
    print("PER-QUESTION RESULTS")
    print("=" * 80)

    for result in results:

        top1 = result["top5"][0]

        status = (
            "PASS"
            if result["document_hit_top1"]
            else "MISS"
        )

        print(
            f"{status} | "
            f"{result['question_id']} | "
            f"Top-1: {top1['document_id']} | "
            f"FAISS: {top1['faiss_score']:.4f} | "
            f"Reranker: {top1['reranker_score']:.4f} | "
            f"P@3: {result['precision_at_3']:.2f}"
        )

    # ========================================================
    # SAVE RESULTS
    # ========================================================

    output_path = Path(
        "data/vectorstore/"
        "reranked_retrieval_evaluation.json"
    )

    evaluation_output = {

        "method":
            "FAISS Top-10 + CrossEncoder reranking",

        "embedding_model":
            EMBEDDING_MODEL_NAME,

        "reranker_model":
            RERANKER_MODEL_NAME,

        "total_questions":
            total,

        "document_metrics": {

            "top1":
                top1_hits / total,

            "top3":
                top3_hits / total,

            "top5":
                top5_hits / total
        },

        "retrieval_precision": {

            "precision_at_1":
                precision_at_1,

            "precision_at_3":
                precision_at_3,

            "precision_at_5":
                precision_at_5
        },

        "results":
            results
    }

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            evaluation_output,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print(
        "Detailed results saved to:",
        output_path
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()