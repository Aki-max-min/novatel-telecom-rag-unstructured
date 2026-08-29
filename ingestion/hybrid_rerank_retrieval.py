import json
import re
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer, CrossEncoder


# ============================================================
# PATHS
# ============================================================

BENCHMARK_PATH = Path("ingestion/retrieval_benchmark.json")
INDEX_PATH = Path("data/vectorstore/faiss.index")
METADATA_PATH = Path("data/vectorstore/chunk_metadata.json")
CHUNK_DIR = Path("data/processed/chunks")

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


# ============================================================
# HYBRID WEIGHTS
# ============================================================

# CrossEncoder remains the main signal.
RERANKER_WEIGHT = 0.80
TITLE_WEIGHT = 0.15
CATEGORY_WEIGHT = 0.05


# ============================================================
# HELPERS
# ============================================================

def tokenize(text):
    """
    Convert text into normalized word tokens.
    """
    return set(
        re.findall(
            r"\b[a-zA-Z0-9]+\b",
            text.lower()
        )
    )


def title_overlap(query, title):
    """
    Calculate simple lexical overlap between
    query words and document title words.
    """

    query_words = tokenize(query)
    title_words = tokenize(title)

    if not query_words or not title_words:
        return 0.0

    overlap = query_words.intersection(title_words)

    return len(overlap) / len(query_words)


def normalize_scores(scores):
    """
    Min-max normalize a list of scores to [0, 1].
    """

    if not scores:
        return []

    min_score = min(scores)
    max_score = max(scores)

    if max_score == min_score:
        return [0.5] * len(scores)

    return [
        (score - min_score) / (max_score - min_score)
        for score in scores
    ]


def load_chunk_text(chunk_id):
    """
    Load the text belonging to a chunk.
    """

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

    return chunk.get("text", "")


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("NOVATEL HYBRID RERANKING EXPERIMENT")
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
    # Load models
    # --------------------------------------------------------

    print("\nLoading embedding model...")

    embedding_model = SentenceTransformer(
        EMBEDDING_MODEL_NAME,
        local_files_only=True
    )

    print("Loading CrossEncoder...")

    reranker = CrossEncoder(
        RERANKER_MODEL_NAME
    )

    # --------------------------------------------------------
    # Load chunk text
    # --------------------------------------------------------

    print("Loading chunk text...")

    chunk_texts = {}

    for doc in metadata:

        chunk_id = doc["chunk_id"]

        chunk_texts[chunk_id] = load_chunk_text(
            chunk_id
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
    # EVALUATION
    # ========================================================

    for item in benchmark:

        question = item["question"]

        expected_ids = set(
            item["expected_document_ids"]
        )

        expected_category = item["category"]

        # ----------------------------------------------------
        # Stage 1: FAISS Top-10
        # ----------------------------------------------------

        query_embedding = embedding_model.encode(
            [question],
            convert_to_numpy=True,
            normalize_embeddings=True
        ).astype("float32")

        scores, indices = index.search(
            query_embedding,
            10
        )

        candidates = []

        for faiss_score, idx in zip(
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

                    "title":
                        doc.get("title", ""),

                    "category":
                        doc.get("category", ""),

                    "department":
                        doc.get("department", ""),

                    "customer_scope":
                        doc.get("customer_scope", ""),

                    "related_ids":
                        doc.get("related_ids", []),

                    "tags":
                        doc.get("tags", []),

                    "text":
                        text,

                    "faiss_score":
                        float(faiss_score)
                }
            )

        # ----------------------------------------------------
        # Stage 2: CrossEncoder
        # ----------------------------------------------------

        pairs = [
            (
                question,
                candidate["text"]
            )
            for candidate in candidates
        ]

        cross_scores = reranker.predict(
            pairs
        )

        for candidate, score in zip(
            candidates,
            cross_scores
        ):

            candidate["crossencoder_score"] = float(
                score
            )

        # ----------------------------------------------------
        # Normalize CrossEncoder scores
        # ----------------------------------------------------

        cross_values = [
            c["crossencoder_score"]
            for c in candidates
        ]

        normalized_cross = normalize_scores(
            cross_values
        )

        # ----------------------------------------------------
        # Calculate hybrid scores
        # ----------------------------------------------------

        for candidate, normalized_ce in zip(
            candidates,
            normalized_cross
        ):

            # -----------------------------------------------
            # Title similarity
            # -----------------------------------------------

            title_score = title_overlap(
                question,
                candidate["title"]
            )

            # -----------------------------------------------
            # Category match
            # -----------------------------------------------

            category_score = (
                1.0
                if candidate["category"]
                == expected_category
                else 0.0
            )

            # -----------------------------------------------
            # Final hybrid score
            # -----------------------------------------------

            hybrid_score = (
                RERANKER_WEIGHT
                * normalized_ce
                +
                TITLE_WEIGHT
                * title_score
                +
                CATEGORY_WEIGHT
                * category_score
            )

            candidate["title_score"] = title_score

            candidate["category_score"] = category_score

            candidate["hybrid_score"] = hybrid_score

        # ----------------------------------------------------
        # Sort by hybrid score
        # ----------------------------------------------------

        reranked = sorted(
            candidates,
            key=lambda x: x["hybrid_score"],
            reverse=True
        )

        # ----------------------------------------------------
        # Evaluate
        # ----------------------------------------------------

        retrieved_ids = [
            candidate["document_id"]
            for candidate in reranked
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

            relevant = sum(
                1
                for candidate in top_k
                if candidate["document_id"]
                in expected_ids
            )

            if k == 0:
                return 0.0

            return relevant / k

        p1 = precision_at_k(1)
        p3 = precision_at_k(3)
        p5 = precision_at_k(5)

        precision_at_1_total += p1
        precision_at_3_total += p3
        precision_at_5_total += p5

        # ----------------------------------------------------
        # Save
        # ----------------------------------------------------

        results.append(
            {
                "question_id":
                    item["question_id"],

                "category":
                    expected_category,

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
    # AGGREGATE
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
    print("HYBRID RERANKED RETRIEVAL RESULTS")
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
    print("HYBRID PRECISION")
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
            f"Hybrid: {top1['hybrid_score']:.4f} | "
            f"CE: {top1['crossencoder_score']:.4f} | "
            f"Title: {top1['title_score']:.2f} | "
            f"Category: {top1['category_score']:.0f} | "
            f"P@3: {result['precision_at_3']:.2f}"
        )

    # ========================================================
    # SAVE RESULTS
    # ========================================================

    output_path = Path(
        "data/vectorstore/"
        "hybrid_reranked_retrieval_evaluation.json"
    )

    output = {
        "method":
            "FAISS Top-10 + CrossEncoder + metadata/title hybrid reranking",

        "embedding_model":
            EMBEDDING_MODEL_NAME,

        "reranker_model":
            RERANKER_MODEL_NAME,

        "weights": {
            "crossencoder":
                RERANKER_WEIGHT,

            "title":
                TITLE_WEIGHT,

            "category":
                CATEGORY_WEIGHT
        },

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
            output,
            f,
            indent=2,
            ensure_ascii=False
        )

    print()
    print(
        "Detailed results saved to:",
        output_path
    )


if __name__ == "__main__":
    main()