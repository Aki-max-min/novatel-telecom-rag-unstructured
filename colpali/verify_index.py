from pathlib import Path
import json
import torch


EMBEDDING_ROOT = Path(
    "data/experiments/public_pdfs/colpali/embeddings"
)

METADATA_ROOT = Path(
    "data/experiments/public_pdfs/colpali/metadata"
)


def main():

    print("=" * 60)
    print("COLPALI INDEX VERIFICATION")
    print("=" * 60)

    # --------------------------------------------------
    # Count embeddings
    # --------------------------------------------------

    embedding_files = sorted(
        EMBEDDING_ROOT.rglob("*.pt")
    )

    print("\nEmbedding files:", len(embedding_files))

    # --------------------------------------------------
    # Count metadata
    # --------------------------------------------------

    metadata_files = sorted(
        METADATA_ROOT.glob("*.json")
    )

    print("Metadata files:", len(metadata_files))

    # --------------------------------------------------
    # Count page images
    # --------------------------------------------------

    image_root = Path(
        "data/experiments/public_pdfs/colpali/page_images"
    )

    image_files = sorted(
        image_root.rglob("*.jpg")
    )

    print("Page images:", len(image_files))

    # --------------------------------------------------
    # Inspect first embedding
    # --------------------------------------------------

    if embedding_files:

        first_embedding = torch.load(
            embedding_files[0],
            map_location="cpu",
            weights_only=True
        )

        print("\nFirst embedding:")
        print("Path:", embedding_files[0])
        print("Shape:", first_embedding.shape)
        print("Dtype:", first_embedding.dtype)
        print("Device:", first_embedding.device)

    # --------------------------------------------------
    # Inspect first metadata
    # --------------------------------------------------

    if metadata_files:

        with open(
            metadata_files[0],
            "r",
            encoding="utf-8"
        ) as f:

            first_metadata = json.load(f)

        print("\nFirst metadata:")
        print(
            json.dumps(
                first_metadata,
                indent=2,
                ensure_ascii=False
            )
        )

    # --------------------------------------------------
    # Final validation
    # --------------------------------------------------

    print("\n" + "-" * 60)

    if (
        len(embedding_files) == 878
        and len(metadata_files) == 878
        and len(image_files) == 878
    ):

        print("STATUS: PASS")
        print("All 878 pages have embeddings, metadata and images.")

    else:

        print("STATUS: CHECK REQUIRED")

        print(
            f"Expected: 878 embeddings, 878 metadata, "
            f"878 images"
        )

    print("=" * 60)


if __name__ == "__main__":
    main()