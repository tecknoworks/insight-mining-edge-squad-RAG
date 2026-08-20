"""Pydantic request/response schemas for the ingestion API surface.

Kept separate from ``app.models.db`` (the SQLAlchemy ORM models) so the
OpenAPI schema this app serves never leaks ORM internals to the generated
frontend client (``client/src/api/``).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DatasetStatus(StrEnum):
    """Lifecycle of an ingested dataset as it moves through the pipeline."""

    INGESTED = "ingested"
    EMBEDDED = "embedded"
    CLUSTERED = "clustered"
    SUMMARIZED = "summarized"


class EmbeddingJobState(StrEnum):
    """Lifecycle of one embedding run for a dataset."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionError(BaseModel):
    """One rejected CSV row, reported back to the caller."""

    row_number: int
    column: str | None = None
    reason: str


class IngestionReport(BaseModel):
    """Result of a CSV upload — accepted/rejected counts and per-row reasons.

    ``dataset_id`` is ``None`` when nothing was persisted (zero valid rows).
    ``errors`` is capped at ``settings.max_reported_errors``; ``rows_rejected``
    always reports the true total regardless of the cap.
    """

    dataset_id: uuid.UUID | None = None
    filename: str
    rows_total: int
    rows_accepted: int
    rows_rejected: int
    errors: list[IngestionError] = []
    errors_truncated: bool = False


class FeedbackItemOut(BaseModel):
    """A single persisted feedback row, as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    feedback_text: str
    submitted_at: datetime | None
    source: str | None
    customer_id: str | None
    row_number: int


class DatasetSummary(BaseModel):
    """Dataset-level metadata, without its feedback items."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: DatasetStatus
    row_count_total: int
    row_count_accepted: int
    row_count_rejected: int
    created_at: datetime


class DatasetDetail(DatasetSummary):
    """Dataset metadata plus every feedback item ingested from it."""

    feedback_items: list[FeedbackItemOut] = []


class EmbeddingJobStatus(BaseModel):
    """The latest embedding run's state for a dataset."""

    model_config = ConfigDict(from_attributes=True)

    dataset_id: uuid.UUID
    state: EmbeddingJobState
    items_total: int
    items_embedded: int
    items_failed: int
    model: str
    dimension: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
