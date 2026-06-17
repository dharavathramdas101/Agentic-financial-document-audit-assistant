"""
Retrieval-layer metrics: Recall@K and MRR.

Both are hand-implemented so every line can be explained in an interview
without citing a library.

Definitions
-----------
Recall@K
    For a single query: fraction of gold pages that appear in the top-K
    retrieved chunks.
    recall@k = |{gold_pages} ∩ {page_num of top-k chunks}| / |{gold_pages}|

    Intuition: if the answer is on pages [25, 40] and we retrieve 10 chunks
    with page_nums [40, 26, 3, ...], recall@10 = 1/2 = 0.5 (only page 40 hit).

Mean Reciprocal Rank (MRR)
    For a single query: 1 / rank of the first relevant chunk.
    If no relevant chunk is in the list: RR = 0.
    MRR = mean(RR) over all queries.

    Intuition: rewards systems that put a relevant chunk at rank 1 vs rank 5.
"""

from __future__ import annotations

from graph.state import Chunk


def recall_at_k(
    retrieved_chunks: list[Chunk],
    gold_pages: list[int],
    k: int,
) -> float:
    """
    Recall@K for a single query.

    Args:
        retrieved_chunks: Ordered list of chunks from the retriever (index 0 = top rank).
        gold_pages:       Pages that contain a correct answer.
        k:                How many top chunks to consider.

    Returns:
        Float in [0, 1]. Returns 0.0 if gold_pages is empty.
    """
    if not gold_pages:
        return 0.0
    top_k_pages = {c["page_num"] for c in retrieved_chunks[:k]}
    hits = len(top_k_pages & set(gold_pages))
    return hits / len(gold_pages)


def reciprocal_rank(
    retrieved_chunks: list[Chunk],
    gold_pages: list[int],
) -> float:
    """
    Reciprocal Rank (RR) for a single query.

    Returns 1/rank of the first chunk whose page_num is in gold_pages,
    or 0.0 if no relevant chunk is found.
    """
    gold_set = set(gold_pages)
    for rank, chunk in enumerate(retrieved_chunks, start=1):
        if chunk["page_num"] in gold_set:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(rr_scores: list[float]) -> float:
    """MRR = average of per-query RR scores."""
    return sum(rr_scores) / len(rr_scores) if rr_scores else 0.0


def compute_retrieval_metrics(
    results: list[dict],
    k_values: list[int] | None = None,
) -> dict:
    """
    Aggregate Recall@K and MRR over a list of per-query result dicts.

    Args:
        results: Each dict must have:
                   "retrieved_chunks": list[Chunk]
                   "gold_pages":       list[int]
        k_values: Which K values to compute recall for. Default: [5, 10].

    Returns:
        Dict with keys like "recall_at_5", "recall_at_10", "mrr".
    """
    if k_values is None:
        k_values = [5, 10]

    recall_accum = {k: [] for k in k_values}
    rr_scores: list[float] = []

    for r in results:
        chunks = r["retrieved_chunks"]
        gold   = r["gold_pages"]
        if not gold:
            continue
        for k in k_values:
            recall_accum[k].append(recall_at_k(chunks, gold, k))
        rr_scores.append(reciprocal_rank(chunks, gold))

    metrics = {f"recall_at_{k}": round(sum(v) / len(v), 4) if v else 0.0
               for k, v in recall_accum.items()}
    metrics["mrr"] = round(mean_reciprocal_rank(rr_scores), 4)
    return metrics
