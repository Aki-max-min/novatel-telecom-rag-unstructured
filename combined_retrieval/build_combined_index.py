from pathlib import Path
import json
import faiss
import numpy as np


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SYNTHETIC_INDEX = PROJECT_ROOT / "data" / "vectorstore" / "faiss.index"
SYNTHETIC_METADATA = PROJECT_ROOT / "data" / "vectorstore" / "chunk_metadata.json"

PUBLIC_INDEX = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "public_pdfs"
    / "vectorstore"
    / "faiss.index"
)

PUBLIC_METADATA = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "public_pdfs"
    / "vectorstore"
    / "chunk_metadata_enriched.json"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "experiments"
    / "combined_retrieval"
    / "vectorstore"
)

OUTPUT_INDEX = OUTPUT_DIR / "faiss.index"
OUTPUT_METADATA = OUTPUT_DIR / "chunk_metadata.json"


# ============================================================
# HELPERS
# ============================================================

def load_metadata(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def reconstruct_index(index):
    """
    Reconstruct all vectors from an existing FAISS index.
    This works because the existing indexes are IndexFlatIP.
    """
    vectors = index.reconstruct_n(0, index.ntotal)
    return np.asarray(vectors, dtype=np.float32)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("BUILDING COMBINED SYNTHETIC + PUBLIC RETRIEVAL INDEX")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # 1. Load Synthetic
    # --------------------------------------------------------

    print("\n[1/6] Loading synthetic index...")

    synthetic_index = faiss.read_index(str(SYNTHETIC_INDEX))
    synthetic_metadata = load_metadata(SYNTHETIC_METADATA)

    print(f"Synthetic FAISS vectors : {synthetic_index.ntotal}")
    print(f"Synthetic metadata      : {len(synthetic_metadata)}")
    print(f"Synthetic dimension     : {synthetic_index.d}")

    # --------------------------------------------------------
    # 2. Load Public PDF
    # --------------------------------------------------------

    print("\n[2/6] Loading public PDF index...")

    public_index = faiss.read_index(str(PUBLIC_INDEX))
    public_metadata = load_metadata(PUBLIC_METADATA)

    print(f"Public FAISS vectors    : {public_index.ntotal}")
    print(f"Public metadata         : {len(public_metadata)}")
    print(f"Public dimension        : {public_index.d}")

    # --------------------------------------------------------
    # 3. Validate
    # --------------------------------------------------------

    print("\n[3/6] Validating inputs...")

    if synthetic_index.ntotal != len(synthetic_metadata):
        raise ValueError(
            "Synthetic index/metadata count mismatch: "
            f"{synthetic_index.ntotal} vs {len(synthetic_metadata)}"
        )

    if public_index.ntotal != len(public_metadata):
        raise ValueError(
            "Public index/metadata count mismatch: "
            f"{public_index.ntotal} vs {len(public_metadata)}"
        )

    if synthetic_index.d != public_index.d:
        raise ValueError(
            "Embedding dimensions do not match: "
            f"{synthetic_index.d} vs {public_index.d}"
        )

    if synthetic_index.metric_type != faiss.METRIC_INNER_PRODUCT:
        raise ValueError("Synthetic index is not Inner Product.")

    if public_index.metric_type != faiss.METRIC_INNER_PRODUCT:
        raise ValueError("Public index is not Inner Product.")

    print("Validation: PASS")

    # --------------------------------------------------------
    # 4. Reconstruct vectors
    # --------------------------------------------------------

    print("\n[4/6] Reconstructing vectors...")

    synthetic_vectors = reconstruct_index(synthetic_index)
    public_vectors = reconstruct_index(public_index)

    print(f"Synthetic matrix shape : {synthetic_vectors.shape}")
    print(f"Public matrix shape    : {public_vectors.shape}")

    # --------------------------------------------------------
    # 5. Combine vectors + metadata
    # --------------------------------------------------------

    print("\n[5/6] Combining corpora...")

    combined_vectors = np.vstack(
        [synthetic_vectors, public_vectors]
    ).astype(np.float32)

    combined_metadata = []

    # Synthetic metadata
    for record in synthetic_metadata:
        record = dict(record)

        record["source_corpus"] = "synthetic"

        # Make sure combined metadata has domain_tags
        if "domain_tags" not in record:
            record["domain_tags"] = record.get("tags", [])

        combined_metadata.append(record)

    # Public metadata
    for record in public_metadata:
        record = dict(record)

        record["source_corpus"] = "public"

        if "domain_tags" not in record:
            record["domain_tags"] = record.get("tags", [])

        combined_metadata.append(record)

    expected_count = (
        synthetic_index.ntotal +
        public_index.ntotal
    )

    if len(combined_metadata) != expected_count:
        raise ValueError(
            "Combined metadata count mismatch: "
            f"{len(combined_metadata)} vs {expected_count}"
        )

    if combined_vectors.shape[0] != expected_count:
        raise ValueError(
            "Combined vector count mismatch: "
            f"{combined_vectors.shape[0]} vs {expected_count}"
        )

    # --------------------------------------------------------
    # 6. Build and save new FAISS index
    # --------------------------------------------------------

    print("\n[6/6] Building combined FAISS index...")

    combined_index = faiss.IndexFlatIP(combined_vectors.shape[1])
    combined_index.add(combined_vectors)

    faiss.write_index(
        combined_index,
        str(OUTPUT_INDEX)
    )

    with open(
        OUTPUT_METADATA,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            combined_metadata,
            f,
            indent=2,
            ensure_ascii=False
        )

    # --------------------------------------------------------
    # Final verification
    # --------------------------------------------------------

    print("\n" + "=" * 70)
    print("COMBINED INDEX CREATED")
    print("=" * 70)

    print(f"Synthetic chunks : {synthetic_index.ntotal}")
    print(f"Public chunks    : {public_index.ntotal}")
    print(f"Combined chunks  : {combined_index.ntotal}")
    print(f"Dimension        : {combined_index.d}")
    print(f"\nIndex saved to:")
    print(OUTPUT_INDEX)

    print(f"\nMetadata saved to:")
    print(OUTPUT_METADATA)

    # Source counts
    synthetic_count = sum(
        1 for x in combined_metadata
        if x.get("source_corpus") == "synthetic"
    )

    public_count = sum(
        1 for x in combined_metadata
        if x.get("source_corpus") == "public"
    )

    print("\nSource verification:")
    print(f"  synthetic = {synthetic_count}")
    print(f"  public    = {public_count}")
    print(f"  total     = {synthetic_count + public_count}")

    if (
        combined_index.ntotal == 1545
        and synthetic_count == 383
        and public_count == 1162
    ):
        print("\nSTATUS: PASS")
    else:
        print("\nSTATUS: FAIL")


if __name__ == "__main__":
    main()
    