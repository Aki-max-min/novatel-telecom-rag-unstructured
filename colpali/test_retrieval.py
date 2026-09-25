from retriever import ColPaliRetriever


def main():

    print("=" * 70)
    print("COLPALI RETRIEVAL TEST")
    print("=" * 70)

    # --------------------------------------------------
    # Initialize retriever
    # --------------------------------------------------

    retriever = ColPaliRetriever()

    # --------------------------------------------------
    # Test query
    # --------------------------------------------------

    query = (
        "What are the regulations for protecting "
        "telecom consumers?"
    )

    # --------------------------------------------------
    # Search
    # --------------------------------------------------

    results = retriever.search(
        query,
        top_k=5
    )

    # --------------------------------------------------
    # Display results
    # --------------------------------------------------

    print("\n" + "=" * 70)
    print("TOP RESULTS")
    print("=" * 70)

    for result in results:

        print(
            f"\nRank: {result['rank']}"
        )

        print(
            f"Score: {result['score']:.4f}"
        )

        print(
            f"Document: {result['pdf_name']}"
        )

        print(
            f"Page: {result['page_number']}"
        )

        print(
            f"Image: {result['image_path']}"
        )

    print("\n" + "=" * 70)
    print("RETRIEVAL TEST COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()