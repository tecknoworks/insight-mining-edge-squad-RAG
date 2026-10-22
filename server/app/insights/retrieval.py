"""Semantic retrieval for chat-with-data.

This is the **only** retrieval SQL in the codebase (route handlers must not
query for feedback items themselves).

The order of operations is the whole point: every filter — dataset, source,
date bounds — is a SQL predicate that *builds the candidate set*, and ranking
happens only over what survives. Post-filtering (rank globally, then filter)
is what this deliberately avoids: with a rare source, the global top-k contains
none of its rows and the filtered result comes back empty, which is both a
correctness bug and, once IM-7 adds tenants, a data-leak boundary.

Ranking is an exact cosine scan over the candidate vectors rather than a query
against the in-memory HNSW index. hnswlib's ``filter=`` predicate gates
result-heap insertion without pruning graph traversal, so a restrictive filter
degenerates into a near-exhaustive walk with a Python callback per visited node
— slower than this scan in exactly the case that matters — while a permissive
one re-enables early termination and returns only an approximate top-k of the
filtered set. Exact is both correct and, at this project's scale, faster. The
HNSW index remains IM-2's deliverable and the substrate for a future
re-ranking/scale ticket.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.db import FeedbackItem
from app.models.schemas import ChatFilters

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedItem:
    """One feedback item retrieved as grounding context, with its distance.

    ``distance`` is cosine *distance* (0 = identical, 2 = opposite), the same
    metric the clustering stage uses, so thresholds are comparable across the
    two.
    """

    id: uuid.UUID
    feedback_text: str
    source: str | None
    submitted_at: datetime | None
    distance: float


def _candidate_query(
    dataset_id: uuid.UUID, filters: ChatFilters | None
) -> Select[tuple[uuid.UUID, bytes | None, str, str | None, datetime | None]]:
    """Build the candidate-set query: every predicate, no ranking, no limit.

    Column-select rather than whole ORM entities — nothing downstream needs a
    persistent object, and it keeps identity-map churn out of the request.
    """
    query = select(
        FeedbackItem.id,
        FeedbackItem.embedding,
        FeedbackItem.feedback_text,
        FeedbackItem.source,
        FeedbackItem.submitted_at,
    ).where(
        FeedbackItem.dataset_id == dataset_id,
        FeedbackItem.embedding.is_not(None),
    )

    if filters is None:
        return query

    # An explicitly empty source list means "no source filter", not "match
    # nothing" — the latter would silently return zero results for a caller
    # that sent `source: []` meaning "any".
    if filters.source:
        query = query.where(FeedbackItem.source.in_(filters.source))

    if filters.date_from is not None:
        start = datetime.combine(filters.date_from, datetime.min.time())
        query = query.where(FeedbackItem.submitted_at >= start)

    if filters.date_to is not None:
        # `date_to` is inclusive of the whole day. `submitted_at` is a
        # timestamp, so `<= date_to` would silently drop everything submitted
        # after midnight on that day.
        exclusive_end = datetime.combine(filters.date_to, datetime.min.time()) + timedelta(days=1)
        query = query.where(FeedbackItem.submitted_at < exclusive_end)

    return query


def retrieve(
    db: Session,
    *,
    dataset_id: uuid.UUID,
    query_vector: list[float],
    filters: ChatFilters | None,
    top_k: int,
    max_distance: float,
    dimension: int,
) -> list[RetrievedItem]:
    """Retrieve the top ``top_k`` most semantically similar feedback items.

    Args:
        db: Database session.
        dataset_id: The only dataset that may contribute candidates.
        query_vector: The embedded question, from ``EmbeddingClient.embed_query``.
        filters: Optional source/date narrowing, applied as SQL predicates.
        top_k: Maximum items to return.
        max_distance: Cosine-distance ceiling; anything above is discarded.
        dimension: Expected embedding dimension, used to reject stale rows.

    Returns:
        Items ordered by ascending distance, all within ``max_distance``.
        Empty when the candidate set is empty or nothing clears the ceiling —
        the caller treats that as "no relevant feedback" and never calls Claude.
    """
    if top_k < 1:
        return []

    rows = db.execute(_candidate_query(dataset_id, filters)).all()
    if not rows:
        logger.info(
            "chat retrieval: dataset %s has no candidates under the given filters", dataset_id
        )
        return []

    expected_bytes = dimension * 4  # float32
    blobs: list[bytes] = []
    kept: list[tuple[uuid.UUID, str, str | None, datetime | None]] = []
    for row in rows:
        embedding = row.embedding
        if embedding is None or len(embedding) != expected_bytes:
            # Nothing invalidates stored embeddings when EMBEDDING_DIMENSION
            # changes, so a stale-dimension blob is a live possibility.
            # np.frombuffer would happily return a wrong-length vector.
            logger.warning(
                "chat retrieval: skipping feedback item %s — embedding is %s bytes, expected %d",
                row.id,
                "NULL" if embedding is None else len(embedding),
                expected_bytes,
            )
            continue
        blobs.append(embedding)
        kept.append((row.id, row.feedback_text, row.source, row.submitted_at))

    if not blobs:
        return []

    matrix = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(-1, dimension)
    query = np.asarray(query_vector, dtype=np.float32)

    query_norm = float(np.linalg.norm(query))
    row_norms = np.linalg.norm(matrix, axis=1)
    denominator = row_norms * query_norm
    # A zero vector has no direction, so cosine is undefined. Assign the
    # maximum distance so such rows sort last and the relevance floor drops
    # them, rather than emitting a warning-free NaN that breaks argsort order.
    similarities = np.divide(
        matrix @ query,
        denominator,
        out=np.full(matrix.shape[0], -1.0, dtype=np.float32),
        where=denominator > 0,
    )
    distances = 1.0 - similarities

    limit = min(top_k, distances.shape[0])
    candidates = np.argpartition(distances, limit - 1)[:limit]
    ordered = candidates[np.argsort(distances[candidates], kind="stable")]

    results: list[RetrievedItem] = []
    for position in ordered:
        distance = float(distances[position])
        if distance > max_distance:
            break  # ascending order — everything after this is further still
        item_id, text, source, submitted_at = kept[position]
        results.append(
            RetrievedItem(
                id=item_id,
                feedback_text=text,
                source=source,
                submitted_at=submitted_at,
                distance=distance,
            )
        )

    logger.info(
        "chat retrieval: %d candidates -> %d within max_distance=%.2f",
        len(kept),
        len(results),
        max_distance,
    )
    return results
