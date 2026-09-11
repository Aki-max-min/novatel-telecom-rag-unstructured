from collections import defaultdict


def reciprocal_rank_fusion(
    ranked_lists,
    k=60
):
    """
    Combine multiple ranked result lists using
    Reciprocal Rank Fusion (RRF).

    Parameters
    ----------
    ranked_lists : list[list[str]]
        Each list contains document IDs ordered
        from best to worst.

    k : int
        RRF constant. Standard value is 60.

    Returns
    -------
    list[tuple[str, float]]
        Documents ranked by their fused RRF score.
    """

    scores = defaultdict(float)

    for ranked_list in ranked_lists:

        for rank, document_id in enumerate(
            ranked_list,
            start=1
        ):

            scores[document_id] += (
                1.0 / (k + rank)
            )

    ranked_documents = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return ranked_documents