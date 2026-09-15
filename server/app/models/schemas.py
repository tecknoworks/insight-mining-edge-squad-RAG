"""Pydantic request/response schemas for the ingestion API surface.

Kept separate from ``app.models.db`` (the SQLAlchemy ORM models) so the
OpenAPI schema this app serves never leaks ORM internals to the generated
frontend client (``client/src/api/``).
"""

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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


class ChatRole(StrEnum):
    """Author of a chat message. Mirrors the Anthropic Messages API's roles."""

    USER = "user"
    ASSISTANT = "assistant"


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


# --- Chat-with-data (RAG) ---------------------------------------------------
#
# The SSE frame payloads below are declared as models so the shapes reach
# ``client/src/api/`` through the OpenAPI schema even though the response body
# itself is a stream the generated client cannot consume (the reader lives in
# ``client/src/lib/chatStream.ts``).


class ChatFilters(BaseModel):
    """Optional scope narrowing for retrieval, applied as SQL predicates.

    ``date_to`` is *inclusive* of the whole day — the retrieval layer converts
    it to ``submitted_at < date_to + 1 day`` because ``submitted_at`` is a
    timestamp, not a date.
    """

    source: list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None


class ChatMessageRequest(BaseModel):
    """Request body for ``POST /chat/messages``.

    ``conversation_id`` is ``None`` to start a new conversation; the assigned
    id comes back on the terminal ``done`` event.
    """

    dataset_id: uuid.UUID
    message: str = Field(min_length=1)
    conversation_id: uuid.UUID | None = None
    filters: ChatFilters | None = None


class ChatCitation(BaseModel):
    """One feedback item the answer actually referenced.

    ``excerpt`` is truncated server-side; ``feedback_item_id`` always belongs
    to the requested dataset because retrieval was dataset-scoped in SQL.
    """

    feedback_item_id: uuid.UUID
    excerpt: str
    source: str | None = None
    date: datetime | None = None


class ChatTokenEvent(BaseModel):
    """``event: token`` — one incremental chunk of the answer."""

    text: str


class ChatCitationsEvent(BaseModel):
    """``event: citations`` — emitted once, after the last token."""

    items: list[ChatCitation]


class ChatDoneEvent(BaseModel):
    """``event: done`` — terminal success frame."""

    conversation_id: uuid.UUID
    message_id: uuid.UUID


class ChatErrorEvent(BaseModel):
    """``event: error`` — terminal failure frame; no ``done`` follows it."""

    message: str


class ChatMessageOut(BaseModel):
    """One persisted turn, as replayed by ``GET /chat/conversations/{id}``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: ChatRole
    content: str
    citations: list[ChatCitation] | None = None
    sequence: int
    created_at: datetime


class ConversationDetail(BaseModel):
    """A conversation and its messages, ordered by ``sequence``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    title: str | None
    created_at: datetime
    messages: list[ChatMessageOut] = []
