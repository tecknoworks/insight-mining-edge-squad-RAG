"""SQLAlchemy ORM models: ``datasets`` and ``feedback_items``.

Subclasses the shared ``Base`` from ``app.core.db`` so Alembic autogenerate
sees these tables. Schema is deliberately left room for IM-7 to add a
nullable ``organization_id`` FK to both tables without a rewrite — no
auth/tenant scoping is implemented here.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.schemas import DatasetStatus, EmbeddingJobState


def _utcnow() -> datetime:
    """Return the current time as a naive UTC ``datetime`` (SQLite has no ``timestamptz``)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Dataset(Base):
    """One uploaded CSV and its ingestion outcome."""

    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[DatasetStatus] = mapped_column(
        Enum(
            DatasetStatus,
            native_enum=False,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=DatasetStatus.INGESTED,
    )
    row_count_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    feedback_items: Mapped[list["FeedbackItem"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="FeedbackItem.row_number",
    )


class FeedbackItem(Base):
    """One accepted row of customer feedback from a dataset's CSV."""

    __tablename__ = "feedback_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    dataset: Mapped["Dataset"] = relationship(back_populates="feedback_items")


class EmbeddingJob(Base):
    """The latest embedding run for a dataset — one row per dataset, reset on each re-run."""

    __tablename__ = "embedding_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    state: Mapped[EmbeddingJobState] = mapped_column(
        Enum(
            EmbeddingJobState,
            native_enum=False,
            validate_strings=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=EmbeddingJobState.PENDING,
    )
    items_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_embedded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str] = mapped_column(String, nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class ClusteringRun(Base):
    """One clustering run for a dataset — multiple runs kept for history."""

    __tablename__ = "clustering_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    algorithm: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    cluster_count: Mapped[int] = mapped_column(Integer, nullable=False)
    noise_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    clusters: Mapped[list["Cluster"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    assignments: Mapped[list["ClusterAssignment"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Cluster(Base):
    """A single cluster from a clustering run."""

    __tablename__ = "clusters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clustering_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cluster_index: Mapped[int] = mapped_column(Integer, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    run: Mapped["ClusteringRun"] = relationship(back_populates="clusters")


class ClusterAssignment(Base):
    """Assignment of a feedback item to a cluster (or noise if cluster_id is NULL)."""

    __tablename__ = "cluster_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clustering_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feedback_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), nullable=True, index=True
    )
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "feedback_item_id", name="uq_cluster_assignments_run_item"),
    )

    run: Mapped["ClusteringRun"] = relationship(back_populates="assignments")
    feedback_item: Mapped["FeedbackItem"] = relationship(foreign_keys=[feedback_item_id])
    cluster: Mapped["Cluster | None"] = relationship(foreign_keys=[cluster_id])
