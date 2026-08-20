"""SQLAlchemy ORM models: ``datasets`` and ``feedback_items``.

Subclasses the shared ``Base`` from ``app.core.db`` so Alembic autogenerate
sees these tables. Schema is deliberately left room for IM-7 to add a
nullable ``organization_id`` FK to both tables without a rewrite — no
auth/tenant scoping is implemented here.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, LargeBinary, String, Text
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
