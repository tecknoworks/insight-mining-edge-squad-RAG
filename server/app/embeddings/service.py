"""Embedding job orchestration: start/resume, batch processing, and job-state persistence.

No route/handler logic lives here — ``app.api.ingestion`` only calls into
this module and maps the result to a status code.
"""

import logging
import uuid
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.embeddings import index as embedding_index
from app.embeddings.client import EmbeddingClient, get_embedding_client
from app.models.db import Dataset, EmbeddingJob, FeedbackItem
from app.models.schemas import DatasetStatus, EmbeddingJobState

logger = logging.getLogger(__name__)


class DatasetNotFoundError(Exception):
    """Raised when the target dataset id does not exist."""


class JobAlreadyRunningError(Exception):
    """Raised when an embedding job for the dataset is already pending/running."""


def _utcnow() -> datetime:
    """Return the current time as a naive UTC ``datetime`` (SQLite has no ``timestamptz``)."""
    return datetime.now(UTC).replace(tzinfo=None)


def start_or_resume_job(db: Session, dataset_id: uuid.UUID) -> EmbeddingJob:
    """Create or reset the dataset's ``embedding_jobs`` row for a new run.

    Raises ``DatasetNotFoundError`` / ``JobAlreadyRunningError`` — the caller
    (route) maps those to 404 / 409.
    """
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise DatasetNotFoundError(f"dataset {dataset_id} not found")

    job = db.execute(
        select(EmbeddingJob).where(EmbeddingJob.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if job is not None and job.state in (EmbeddingJobState.PENDING, EmbeddingJobState.RUNNING):
        raise JobAlreadyRunningError(
            f"an embedding job for dataset {dataset_id} is already running"
        )

    settings = get_settings()
    items_total = db.execute(
        select(func.count())
        .select_from(FeedbackItem)
        .where(FeedbackItem.dataset_id == dataset_id, FeedbackItem.embedding.is_(None))
    ).scalar_one()

    if job is None:
        job = EmbeddingJob(dataset_id=dataset_id)
        db.add(job)

    now = _utcnow()
    job.items_total = items_total
    job.items_embedded = 0
    job.items_failed = 0
    job.model = settings.embedding_model
    job.dimension = settings.embedding_dimension
    job.error = None
    job.started_at = now

    if items_total == 0:
        # Nothing to embed: complete synchronously, no background task needed
        # and zero model inference calls (AC 2).
        job.state = EmbeddingJobState.COMPLETED
        job.finished_at = now
        if dataset.status == DatasetStatus.INGESTED:
            dataset.status = DatasetStatus.EMBEDDED
    else:
        job.state = EmbeddingJobState.PENDING
        job.finished_at = None

    db.commit()
    db.refresh(job)
    return job


def run_job(
    dataset_id: uuid.UUID,
    embedding_client: EmbeddingClient | None = None,
    batch_size: int | None = None,
) -> None:
    """Run one embedding job to completion — the ``BackgroundTasks`` target.

    Opens its own session: the request-scoped session from ``Depends(get_db)``
    is not safe to reuse here, since it may already be torn down by the time
    this background task runs. ``batch_size`` defaults to
    ``settings.embedding_batch_size``; overriding it is for tests only.
    """
    client = embedding_client or get_embedding_client()
    effective_batch_size = batch_size or get_settings().embedding_batch_size
    db = SessionLocal()
    try:
        job = db.execute(
            select(EmbeddingJob).where(EmbeddingJob.dataset_id == dataset_id)
        ).scalar_one()
        job.state = EmbeddingJobState.RUNNING
        db.commit()

        try:
            _process_batches(db, dataset_id, job, client, effective_batch_size)
        except Exception as exc:  # noqa: BLE001 - failure is recorded on the job, not re-raised
            logger.exception("Embedding job failed for dataset %s", dataset_id)
            job.state = EmbeddingJobState.FAILED
            job.error = str(exc)
            job.finished_at = _utcnow()
            db.commit()
            return

        job.state = EmbeddingJobState.COMPLETED
        job.finished_at = _utcnow()
        dataset = db.get(Dataset, dataset_id)
        if dataset is not None and dataset.status == DatasetStatus.INGESTED:
            dataset.status = DatasetStatus.EMBEDDED
        db.commit()
    finally:
        embedding_index.build_index(db)
        db.close()


def _process_batches(
    db: Session,
    dataset_id: uuid.UUID,
    job: EmbeddingJob,
    client: EmbeddingClient,
    batch_size: int,
) -> None:
    """Embed every un-embedded row for the dataset, one batch at a time.

    Fail-fast: on the first batch failure, that batch's rows are counted in
    ``items_failed`` and left ``NULL``; earlier committed batches are
    unaffected, and later batches are never attempted in this run — they are
    picked up by ``items_total`` on the next ``POST``.
    """
    while True:
        rows = list(
            db.execute(
                select(FeedbackItem)
                .where(FeedbackItem.dataset_id == dataset_id, FeedbackItem.embedding.is_(None))
                .order_by(FeedbackItem.row_number)
                .limit(batch_size)
            ).scalars()
        )
        if not rows:
            return

        try:
            vectors = client.embed_documents(
                [row.feedback_text for row in rows], ids=[str(row.id) for row in rows]
            )
            for row, vector in zip(rows, vectors, strict=True):
                row.embedding = np.asarray(vector, dtype=np.float32).tobytes()
            job.items_embedded += len(rows)
            db.commit()
        except Exception:
            db.rollback()
            job.items_failed = len(rows)
            db.commit()
            raise
