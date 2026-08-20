"""Unit tests for the embeddings client, index, and job service.

Everything here runs against a stub ``EmbeddingClient`` / fake tokenizer —
no real ``sentence-transformers`` model load, no network call.
"""

import logging
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base
from app.embeddings import index as embedding_index
from app.embeddings.client import truncate_texts
from app.embeddings.service import (
    DatasetNotFoundError,
    JobAlreadyRunningError,
    run_job,
    start_or_resume_job,
)
from app.ingestion.service import ingest_csv
from app.models.db import Dataset, EmbeddingJob, FeedbackItem
from app.models.schemas import DatasetStatus, EmbeddingJobState

FIXTURES = Path(__file__).parent / "fixtures"
DIMENSION = 4


class _FakeTokenizer:
    """Deterministic, reversible char-level tokenizer stub — not real BPE."""

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        return [ord(char) for char in text]

    def decode(self, token_ids: list[int], skip_special_tokens: bool = True) -> str:
        return "".join(chr(token_id) for token_id in token_ids)


class StubEmbeddingClient:
    """A fake ``EmbeddingClient`` recording every call it receives.

    ``fail_on_call`` (1-based) makes the Nth ``embed_documents`` call raise,
    to exercise the batch-failure path without touching a real model.
    """

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.calls: list[list[str]] = []

    def embed_documents(
        self, texts: list[str], *, ids: Sequence[str] | None = None
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise RuntimeError("simulated embedding failure")
        return [[float(len(text))] * DIMENSION for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@pytest.fixture(autouse=True)
def _embedding_dimension_matches_the_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    # StubEmbeddingClient always returns DIMENSION-length vectors; build_index
    # validates real vector length against settings, so the two must agree.
    monkeypatch.setattr(get_settings(), "embedding_dimension", DIMENSION)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    # StaticPool + a single shared connection so run_job's independently
    # opened SessionLocal() sees the same in-memory database as this session.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr("app.embeddings.service.SessionLocal", testing_session_local)

    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


def _ingest_happy_path(db: Session) -> uuid.UUID:
    def _open(name: str) -> BinaryIO:
        return (FIXTURES / name).open("rb")

    with _open("happy_path.csv") as f:
        report = ingest_csv(db, "happy_path.csv", f)
    assert report.dataset_id is not None
    return report.dataset_id


# --- truncation (client.truncate_texts) -------------------------------------


def test_truncate_texts_leaves_short_text_untouched() -> None:
    result = truncate_texts(["hello"], _FakeTokenizer(), max_seq_length=10)
    assert result == ["hello"]


def test_truncate_texts_truncates_long_text_deterministically() -> None:
    text = "a" * 20
    first = truncate_texts([text], _FakeTokenizer(), max_seq_length=10)
    second = truncate_texts([text], _FakeTokenizer(), max_seq_length=10)
    assert first == second == ["a" * 10]


def test_truncate_texts_logs_with_the_given_identifier(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        truncate_texts(["b" * 20], _FakeTokenizer(), max_seq_length=5, ids=["item-123"])
    assert "item-123" in caplog.text


# --- HNSW index --------------------------------------------------------------


def test_build_index_and_search_orders_by_ascending_cosine_distance(db: Session) -> None:
    dataset_id = _ingest_happy_path(db)
    items = list(db.query(FeedbackItem).filter(FeedbackItem.dataset_id == dataset_id))
    assert len(items) == 3

    # Item 0 is closest to the query, item 2 is furthest (orthogonal-ish).
    vectors = [
        [1.0, 0.0, 0.0, 0.0],
        [0.9, 0.1, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
    ]
    for item, vector in zip(items, vectors, strict=True):
        item.embedding = np.asarray(vector, dtype=np.float32).tobytes()
    db.commit()

    embedding_index.build_index(db)
    results = embedding_index.search([1.0, 0.0, 0.0, 0.0], k=3)

    assert len(results) == 3
    result_ids = [item_id for item_id, _distance in results]
    assert result_ids[0] == items[0].id
    assert result_ids[-1] == items[2].id
    distances = [distance for _item_id, distance in results]
    assert distances == sorted(distances)


def test_build_index_empty_when_no_rows_embedded(db: Session) -> None:
    _ingest_happy_path(db)
    embedding_index.build_index(db)
    assert embedding_index.search([1.0, 0.0, 0.0, 0.0], k=3) == []


# --- job service: batching, idempotency, resume-after-failure ---------------


def test_start_or_resume_job_unknown_dataset_raises(db: Session) -> None:
    with pytest.raises(DatasetNotFoundError):
        start_or_resume_job(db, uuid.uuid4())


def test_run_job_embeds_every_row_in_batches(db: Session) -> None:
    dataset_id = _ingest_happy_path(db)
    start_or_resume_job(db, dataset_id)

    stub = StubEmbeddingClient()
    run_job(dataset_id, embedding_client=stub)
    db.expire_all()  # run_job commits via its own session; refresh this session's view

    job = db.query(EmbeddingJob).filter(EmbeddingJob.dataset_id == dataset_id).one()
    assert job.state == EmbeddingJobState.COMPLETED
    assert job.items_total == 3
    assert job.items_embedded == 3
    assert job.items_failed == 0

    items = list(db.query(FeedbackItem).filter(FeedbackItem.dataset_id == dataset_id))
    embeddings = [item.embedding for item in items]
    assert all(embedding is not None for embedding in embeddings)
    assert all(len(embedding) == DIMENSION * 4 for embedding in embeddings if embedding)  # float32


def test_batches_split_exactly_at_batch_size_with_partial_final_batch(db: Session) -> None:
    dataset = Dataset(
        filename="five_rows.csv",
        status=DatasetStatus.INGESTED,
        row_count_total=5,
        row_count_accepted=5,
        row_count_rejected=0,
    )
    db.add(dataset)
    db.flush()
    for row_number in range(1, 6):
        db.add(
            FeedbackItem(
                dataset_id=dataset.id, feedback_text=f"text {row_number}", row_number=row_number
            )
        )
    db.commit()

    start_or_resume_job(db, dataset.id)
    stub = StubEmbeddingClient()
    run_job(dataset.id, embedding_client=stub, batch_size=2)
    db.expire_all()

    assert [len(call) for call in stub.calls] == [2, 2, 1]
    job = db.query(EmbeddingJob).filter(EmbeddingJob.dataset_id == dataset.id).one()
    assert job.items_embedded == 5
    assert job.state == EmbeddingJobState.COMPLETED


def test_rerun_on_fully_embedded_dataset_is_a_noop(db: Session) -> None:
    dataset_id = _ingest_happy_path(db)
    start_or_resume_job(db, dataset_id)
    stub = StubEmbeddingClient()
    run_job(dataset_id, embedding_client=stub)
    db.expire_all()

    job = start_or_resume_job(db, dataset_id)
    assert job.items_total == 0

    stub.calls.clear()
    run_job(dataset_id, embedding_client=stub)
    db.expire_all()
    assert stub.calls == []

    job = db.query(EmbeddingJob).filter(EmbeddingJob.dataset_id == dataset_id).one()
    assert job.state == EmbeddingJobState.COMPLETED
    assert job.items_embedded == 0


def test_start_or_resume_job_conflicts_while_running(db: Session) -> None:
    dataset_id = _ingest_happy_path(db)
    job = start_or_resume_job(db, dataset_id)
    job.state = EmbeddingJobState.RUNNING
    db.commit()

    with pytest.raises(JobAlreadyRunningError):
        start_or_resume_job(db, dataset_id)


def test_batch_failure_persists_prior_batches_and_marks_failed(db: Session) -> None:
    dataset_id = _ingest_happy_path(db)
    start_or_resume_job(db, dataset_id)

    stub = StubEmbeddingClient(fail_on_call=2)
    run_job(dataset_id, embedding_client=stub, batch_size=1)
    db.expire_all()

    job = db.query(EmbeddingJob).filter(EmbeddingJob.dataset_id == dataset_id).one()
    assert job.state == EmbeddingJobState.FAILED
    assert job.items_embedded == 1
    assert job.items_failed == 1
    assert job.error is not None

    items = list(
        db.query(FeedbackItem)
        .filter(FeedbackItem.dataset_id == dataset_id)
        .order_by(FeedbackItem.row_number)
    )
    assert items[0].embedding is not None
    assert items[1].embedding is None
    assert items[2].embedding is None

    # Resuming picks up exactly the rows still missing an embedding.
    resumed_job = start_or_resume_job(db, dataset_id)
    assert resumed_job.items_total == 2
    stub2 = StubEmbeddingClient()
    run_job(dataset_id, embedding_client=stub2)
    db.expire_all()
    final_job = db.query(EmbeddingJob).filter(EmbeddingJob.dataset_id == dataset_id).one()
    assert final_job.state == EmbeddingJobState.COMPLETED
    assert all(
        item.embedding is not None
        for item in db.query(FeedbackItem).filter(FeedbackItem.dataset_id == dataset_id)
    )
