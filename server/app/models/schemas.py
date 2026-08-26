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


class ClusteringRun(BaseModel):
    """A clustering run — maps feedback items to semantic clusters."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    algorithm: str
    params: dict[str, object]
    random_seed: int
    cluster_count: int
    noise_count: int
    is_current: bool
    created_at: datetime


class Cluster(BaseModel):
    """One semantic cluster from a clustering run."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    cluster_index: int
    item_count: int
    label: str | None
    summary: str | None
    created_at: datetime


class ClusterSummary(BaseModel):
    """Lightweight cluster info (for listing)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cluster_index: int
    item_count: int
    label: str | None


class ClusterAssignmentPoint(BaseModel):
    """One point in the cluster visualization map."""

    feedback_item_id: uuid.UUID
    cluster_id: uuid.UUID | None
    x: float
    y: float


class ClusterMap(BaseModel):
    """Flat payload for cluster visualization — all points + cluster metadata."""

    points: list[ClusterAssignmentPoint]
    clusters: list[ClusterSummary]


class ClusterItemPage(BaseModel):
    """One feedback item as returned by the cluster items endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    feedback_text: str
    source: str | None
    submitted_at: datetime | None
    customer_id: str | None


class ClusterItemsPage(BaseModel):
    """Paginated list of feedback items in a cluster."""

    items: list[ClusterItemPage]


class ClusterSummaryQuote(BaseModel):
    """One representative quote from a cluster summary."""

    text: str
    feedback_item_id: uuid.UUID


class ClusterSummaryResponse(BaseModel):
    """Claude-generated summary for a cluster with label, summary, and quotes."""

    model_config = ConfigDict(from_attributes=True)

    cluster_id: uuid.UUID
    label: str
    summary: str
    quotes: list[ClusterSummaryQuote]
    cached_at: datetime
