"""In-memory HNSW similarity index over embedded feedback items.

Cosine is the distance metric for the whole project — clustering (IM-3) and
retrieval (IM-6) must use the same one. ``hnswlib`` requires integer labels,
not UUIDs, so a parallel label -> ``feedback_item_id`` list is kept alongside
the index and rebuilt together with it. Rebuilt from scratch on every call
(no incremental updates) — simple at this data scale; a later optimization,
not required here.
"""

import uuid

import hnswlib
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.db import FeedbackItem

_index: hnswlib.Index | None = None
_labels: list[uuid.UUID] = []


def build_index(db: Session) -> None:
    """Rebuild the in-memory HNSW index from every row with a non-``NULL`` embedding."""
    global _index, _labels

    settings = get_settings()
    rows = db.execute(
        select(FeedbackItem.id, FeedbackItem.embedding).where(FeedbackItem.embedding.is_not(None))
    ).all()

    if not rows:
        _index = None
        _labels = []
        return

    vectors = np.stack([np.frombuffer(embedding, dtype=np.float32) for _row_id, embedding in rows])
    index = hnswlib.Index(space="cosine", dim=settings.embedding_dimension)
    index.init_index(max_elements=len(rows))
    index.add_items(vectors, list(range(len(rows))))

    _index = index
    _labels = [row_id for row_id, _embedding in rows]


def search(query_vector: list[float], k: int) -> list[tuple[uuid.UUID, float]]:
    """Return up to ``k`` nearest neighbors to ``query_vector``, ascending by cosine distance."""
    if _index is None or not _labels:
        return []

    k = min(k, len(_labels))
    _index.set_ef(max(50, k))
    query = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
    label_indices, distances = _index.knn_query(query, k=k)

    return [
        (_labels[label], float(distance))
        for label, distance in zip(label_indices[0], distances[0], strict=True)
    ]
