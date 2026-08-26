"""Shared test fixtures for the test suite."""

from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.ingestion.service import ingest_csv
from app.models.db import Dataset, FeedbackItem

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db() -> Iterator[Session]:
    """In-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_dataset(db: Session):
    """A dataset with ingested feedback items (no embeddings)."""

    def _open(name: str) -> BinaryIO:
        return (FIXTURES / name).open("rb")

    with _open("happy_path.csv") as f:
        report = ingest_csv(db, "happy_path.csv", f)

    assert report.dataset_id is not None
    dataset = db.get(Dataset, report.dataset_id)
    assert dataset is not None
    return dataset


@pytest.fixture
def sample_dataset_with_embeddings(db: Session):
    """A dataset with ingested feedback items and embeddings."""

    def _open(name: str) -> BinaryIO:
        return (FIXTURES / name).open("rb")

    with _open("happy_path.csv") as f:
        report = ingest_csv(db, "happy_path.csv", f)

    assert report.dataset_id is not None
    dataset = db.get(Dataset, report.dataset_id)

    # Add embeddings to all feedback items
    items = db.execute(
        select(FeedbackItem).where(FeedbackItem.dataset_id == dataset.id)
    ).scalars().all()
    for i, item in enumerate(items):
        vector = np.random.RandomState(42 + i).randn(384).astype(np.float32)
        item.embedding = vector.tobytes()

    db.commit()
    return dataset
