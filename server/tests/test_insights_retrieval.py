"""Unit tests for chat retrieval.

Uses a small embedding dimension so the expected cosine distances are readable
by hand — ``retrieve`` takes ``dimension`` as a parameter, so nothing here
depends on the real 384-dim model.
"""

from datetime import date, datetime

import numpy as np
import pytest
from sqlalchemy.orm import Session

from app.insights.retrieval import retrieve
from app.models.db import Dataset, FeedbackItem
from app.models.schemas import ChatFilters

DIM = 4

# Unit vectors with hand-checkable cosine distances against QUERY.
QUERY = [1.0, 0.0, 0.0, 0.0]
EXACT = [1.0, 0.0, 0.0, 0.0]  # distance 0.0
NEAR = [0.8, 0.6, 0.0, 0.0]  # distance 0.2
ORTHOGONAL = [0.0, 1.0, 0.0, 0.0]  # distance 1.0


def _make_dataset(db: Session, filename: str = "corpus.csv") -> Dataset:
    dataset = Dataset(filename=filename)
    db.add(dataset)
    db.flush()
    return dataset


def _add_item(
    db: Session,
    dataset: Dataset,
    *,
    text: str,
    vector: list[float] | None = None,
    raw_embedding: bytes | None = None,
    source: str | None = None,
    submitted_at: datetime | None = None,
    row_number: int = 0,
) -> FeedbackItem:
    if raw_embedding is None and vector is not None:
        raw_embedding = np.asarray(vector, dtype=np.float32).tobytes()
    item = FeedbackItem(
        dataset_id=dataset.id,
        feedback_text=text,
        source=source,
        submitted_at=submitted_at,
        row_number=row_number,
        embedding=raw_embedding,
    )
    db.add(item)
    db.flush()
    return item


def _retrieve(db: Session, dataset: Dataset, **overrides):
    kwargs = {
        "dataset_id": dataset.id,
        "query_vector": QUERY,
        "filters": None,
        "top_k": 10,
        "max_distance": 2.0,  # effectively no floor unless a test sets one
        "dimension": DIM,
    }
    kwargs.update(overrides)
    return retrieve(db, **kwargs)


def test_orders_by_ascending_distance(db: Session):
    """Closest item first; distances match hand-computed cosine values."""
    dataset = _make_dataset(db)
    _add_item(db, dataset, text="orthogonal", vector=ORTHOGONAL, row_number=1)
    _add_item(db, dataset, text="exact", vector=EXACT, row_number=2)
    _add_item(db, dataset, text="near", vector=NEAR, row_number=3)
    db.commit()

    results = _retrieve(db, dataset)

    assert [item.feedback_text for item in results] == ["exact", "near", "orthogonal"]
    assert results[0].distance == pytest.approx(0.0, abs=1e-6)
    assert results[1].distance == pytest.approx(0.2, abs=1e-6)
    assert results[2].distance == pytest.approx(1.0, abs=1e-6)


def test_restricted_to_requested_dataset(db: Session):
    """An identical item in another dataset is never a candidate."""
    wanted = _make_dataset(db, "wanted.csv")
    other = _make_dataset(db, "other.csv")
    _add_item(db, wanted, text="mine", vector=NEAR)
    _add_item(db, other, text="theirs", vector=EXACT)  # closer, but out of scope
    db.commit()

    results = _retrieve(db, wanted)

    assert [item.feedback_text for item in results] == ["mine"]


def test_source_filter_returns_rare_matches_not_zero(db: Session):
    """AC 4: filters build the candidate set, so a rare source still returns its rows.

    Under post-filtering (rank globally, then filter) this returns zero: the
    global top-3 is entirely 'bulk', and intersecting that with 'rare' is
    empty. This is the test that pins the ordering.
    """
    dataset = _make_dataset(db)
    for index in range(50):
        _add_item(
            db, dataset, text=f"bulk {index}", vector=EXACT, source="bulk", row_number=index
        )
    _add_item(db, dataset, text="rare one", vector=NEAR, source="rare", row_number=99)
    db.commit()

    results = _retrieve(
        db, dataset, top_k=3, filters=ChatFilters(source=["rare"])
    )

    assert [item.feedback_text for item in results] == ["rare one"]


def test_ranking_is_exact_against_brute_force(db: Session):
    """AC 3: the returned order equals a brute-force cosine ranking."""
    rng = np.random.RandomState(7)
    dataset = _make_dataset(db)
    vectors: dict[str, np.ndarray] = {}
    for index in range(40):
        vector = rng.randn(DIM).astype(np.float32)
        text = f"item {index}"
        vectors[text] = vector
        _add_item(db, dataset, text=text, vector=vector.tolist(), row_number=index)
    db.commit()

    results = _retrieve(db, dataset, top_k=40)

    query = np.asarray(QUERY, dtype=np.float32)
    expected = sorted(
        vectors,
        key=lambda text: 1.0
        - float(
            vectors[text] @ query / (np.linalg.norm(vectors[text]) * np.linalg.norm(query))
        ),
    )
    assert [item.feedback_text for item in results] == expected


def test_relevance_floor_discards_distant_items(db: Session):
    """Items beyond max_distance are dropped; nothing surviving yields []."""
    dataset = _make_dataset(db)
    _add_item(db, dataset, text="near", vector=NEAR, row_number=1)
    _add_item(db, dataset, text="far", vector=ORTHOGONAL, row_number=2)
    db.commit()

    kept = _retrieve(db, dataset, max_distance=0.5)
    assert [item.feedback_text for item in kept] == ["near"]

    assert _retrieve(db, dataset, max_distance=0.1) == []


def test_top_k_limits_results(db: Session):
    dataset = _make_dataset(db)
    for index in range(10):
        _add_item(db, dataset, text=f"item {index}", vector=NEAR, row_number=index)
    db.commit()

    assert len(_retrieve(db, dataset, top_k=4)) == 4


def test_top_k_below_one_returns_empty(db: Session):
    dataset = _make_dataset(db)
    _add_item(db, dataset, text="item", vector=EXACT)
    db.commit()

    assert _retrieve(db, dataset, top_k=0) == []


def test_date_to_includes_the_whole_final_day(db: Session):
    """`date_to` is inclusive: a timestamp late on that day must survive.

    A naive `submitted_at <= date_to` implementation silently drops everything
    after midnight, which this catches.
    """
    dataset = _make_dataset(db)
    _add_item(
        db,
        dataset,
        text="late on the last day",
        vector=EXACT,
        submitted_at=datetime(2026, 3, 31, 23, 59, 59),
        row_number=1,
    )
    _add_item(
        db,
        dataset,
        text="next day",
        vector=EXACT,
        submitted_at=datetime(2026, 4, 1, 0, 0, 1),
        row_number=2,
    )
    db.commit()

    results = _retrieve(db, dataset, filters=ChatFilters(date_to=date(2026, 3, 31)))

    assert [item.feedback_text for item in results] == ["late on the last day"]


def test_date_from_excludes_earlier_items(db: Session):
    dataset = _make_dataset(db)
    _add_item(
        db,
        dataset,
        text="too early",
        vector=EXACT,
        submitted_at=datetime(2026, 2, 28, 12, 0),
        row_number=1,
    )
    _add_item(
        db,
        dataset,
        text="in range",
        vector=EXACT,
        submitted_at=datetime(2026, 3, 1, 0, 0),
        row_number=2,
    )
    db.commit()

    results = _retrieve(db, dataset, filters=ChatFilters(date_from=date(2026, 3, 1)))

    assert [item.feedback_text for item in results] == ["in range"]


def test_date_filter_excludes_undated_items(db: Session):
    """Filtering by date means "dated, and in range" — NULL cannot satisfy that."""
    dataset = _make_dataset(db)
    _add_item(db, dataset, text="undated", vector=EXACT, submitted_at=None)
    db.commit()

    assert _retrieve(db, dataset, filters=ChatFilters(date_from=date(2026, 1, 1))) == []


def test_empty_source_list_is_not_a_filter(db: Session):
    """`source: []` means "any", not "none" — otherwise it silently returns nothing."""
    dataset = _make_dataset(db)
    _add_item(db, dataset, text="item", vector=EXACT, source="support")
    db.commit()

    results = _retrieve(db, dataset, filters=ChatFilters(source=[]))

    assert [item.feedback_text for item in results] == ["item"]


def test_skips_stale_dimension_embeddings(db: Session):
    """A wrong-length blob is skipped, not reinterpreted.

    Nothing invalidates stored embeddings when EMBEDDING_DIMENSION changes, and
    np.frombuffer would happily decode a wrong-length buffer.
    """
    dataset = _make_dataset(db)
    _add_item(
        db,
        dataset,
        text="stale 8-dim row",
        raw_embedding=np.zeros(8, dtype=np.float32).tobytes(),
        row_number=1,
    )
    _add_item(db, dataset, text="good row", vector=EXACT, row_number=2)
    db.commit()

    results = _retrieve(db, dataset)

    assert [item.feedback_text for item in results] == ["good row"]


def test_unembedded_items_are_not_candidates(db: Session):
    dataset = _make_dataset(db)
    _add_item(db, dataset, text="not embedded", raw_embedding=None, row_number=1)
    db.commit()

    assert _retrieve(db, dataset) == []


def test_zero_vector_sorts_last_and_is_dropped_by_the_floor(db: Session):
    """A zero vector has no direction; it must not produce NaN and break ordering."""
    dataset = _make_dataset(db)
    _add_item(
        db,
        dataset,
        text="zero",
        raw_embedding=np.zeros(DIM, dtype=np.float32).tobytes(),
        row_number=1,
    )
    _add_item(db, dataset, text="real", vector=NEAR, row_number=2)
    db.commit()

    ordered = _retrieve(db, dataset)
    assert [item.feedback_text for item in ordered] == ["real", "zero"]
    assert ordered[1].distance == pytest.approx(2.0, abs=1e-6)

    assert [item.feedback_text for item in _retrieve(db, dataset, max_distance=1.0)] == ["real"]


def test_empty_dataset_returns_empty(db: Session):
    dataset = _make_dataset(db)
    db.commit()

    assert _retrieve(db, dataset) == []
