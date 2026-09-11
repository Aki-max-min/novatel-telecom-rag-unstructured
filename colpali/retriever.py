from pathlib import Path
import json

import torch

from embedder import ColPaliEmbedder


# ============================================================
# PATHS
# ============================================================

EMBEDDING_ROOT = Path(
    "data/experiments/public_pdfs/colpali/embeddings"
)

METADATA_ROOT = Path(
    "data/experiments/public_pdfs/colpali/metadata"
)


class ColPaliRetriever:

    def __init__(self):

        print("Initializing ColPali retriever...")

        self.embedder = ColPaliEmbedder()

        self.processor = self.embedder.processor

        self.device = self.embedder.device

        # ----------------------------------------------------
        # Load page embeddings
        # ----------------------------------------------------

        print("\nLoading page embeddings...")

        self.embeddings = []
        self.metadata = []

        embedding_files = sorted(
            EMBEDDING_ROOT.rglob("*.pt")
        )

        metadata_files = sorted(
            METADATA_ROOT.glob("*.json")
        )

        print(
            f"Embedding files found: "
            f"{len(embedding_files)}"
        )

        print(
            f"Metadata files found: "
            f"{len(metadata_files)}"
        )

        # ----------------------------------------------------
        # Load embeddings
        # ----------------------------------------------------

        for embedding_path in embedding_files:

            embedding = torch.load(
                embedding_path,
                map_location="cpu",
                weights_only=True
            )

            self.embeddings.append(embedding)

        # ----------------------------------------------------
        # Load metadata
        # ----------------------------------------------------

        for metadata_path in metadata_files:

            with open(
                metadata_path,
                "r",
                encoding="utf-8"
            ) as f:

                metadata = json.load(f)

            self.metadata.append(metadata)

        # ----------------------------------------------------
        # Verify alignment
        # ----------------------------------------------------

        if len(self.embeddings) != len(self.metadata):

            raise ValueError(
                "Number of embeddings does not match "
                "number of metadata records."
            )

        print(
            f"\nLoaded {len(self.embeddings)} pages."
        )

        print("Retriever ready.")

    # ========================================================
    # QUERY
    # ========================================================

    def search(self, query, top_k=5):

        print(f"\nQuery: {query}")

        # ----------------------------------------------------
        # Generate query representation
        # ----------------------------------------------------

        query_embedding = (
            self.embedder.embed_query(query)
        )

        # ----------------------------------------------------
        # Score pages
        # ----------------------------------------------------

        scores = []

        for embedding in self.embeddings:

            # Move one page representation to GPU
            document_embedding = (
                embedding.to(self.device)
            )

            with torch.no_grad():

                score = self.processor.score_retrieval(
                    query_embedding,
                    document_embedding
                )

            scores.append(
                float(score.item())
            )

            del document_embedding

        # ----------------------------------------------------
        # Rank results
        # ----------------------------------------------------

        ranked_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )

        # ----------------------------------------------------
        # Return top-k
        # ----------------------------------------------------

        results = []

        for rank, index in enumerate(
            ranked_indices[:top_k],
            start=1
        ):

            result = dict(
                self.metadata[index]
            )

            result["rank"] = rank
            result["score"] = scores[index]

            results.append(result)

        return results