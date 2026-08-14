"""Ingestion orchestration: stream a CSV, persist accepted rows in batches,
and assemble the resulting :class:`IngestionReport`.

No parsing or persistence logic lives outside this package — the API layer
(``app.api.ingestion``) only calls into here and returns what it gets back.
"""

import csv
import io
import uuid
from dataclasses import dataclass, field
from typing import BinaryIO

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.parser import FEEDBACK_TEXT_COLUMN, ParsedRow, build_column_map, parse_row
from app.models.db import Dataset, FeedbackItem
from app.models.schemas import DatasetStatus, IngestionError, IngestionReport


class HeaderValidationError(Exception):
    """Raised when the CSV header row is missing the required ``feedback_text`` column."""


@dataclass
class _Counters:
    rows_total: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    errors: list[IngestionError] = field(default_factory=list)
    errors_truncated: bool = False


def ingest_csv(db: Session, filename: str, raw_stream: BinaryIO) -> IngestionReport:
    """Parse ``raw_stream`` as a feedback CSV and persist accepted rows.

    Raises ``HeaderValidationError`` if the header row lacks ``feedback_text``
    — nothing is persisted in that case. Otherwise returns an
    ``IngestionReport``; when zero rows were accepted, ``dataset_id`` is
    ``None`` and no ``Dataset`` row is persisted.
    """
    settings = get_settings()
    text_stream = io.TextIOWrapper(raw_stream, encoding="utf-8-sig", newline="")
    reader = csv.reader(text_stream)

    try:
        header_row = next(reader)
    except StopIteration:
        header_row = []

    column_map = build_column_map(header_row)
    if FEEDBACK_TEXT_COLUMN not in column_map:
        raise HeaderValidationError(
            f"header row is missing the required '{FEEDBACK_TEXT_COLUMN}' column"
        )

    dataset_id = uuid.uuid4()
    dataset = Dataset(
        id=dataset_id,
        filename=filename,
        status=DatasetStatus.INGESTED,
        row_count_total=0,
        row_count_accepted=0,
        row_count_rejected=0,
    )
    db.add(dataset)

    counters = _Counters()
    pending_rows: list[tuple[int, ParsedRow]] = []

    for row_number, cells in enumerate(reader, start=1):
        counters.rows_total += 1
        parsed, error = parse_row(cells, column_map)
        if error is not None:
            counters.rows_rejected += 1
            _record_error(
                counters, settings.max_reported_errors, row_number, error.column, error.reason
            )
            continue

        assert parsed is not None  # parse_row guarantees exactly one of parsed/error is set
        pending_rows.append((row_number, parsed))
        if len(pending_rows) >= settings.internal_batch_size:
            _flush_batch(
                db, dataset, dataset_id, pending_rows, counters, settings.max_reported_errors
            )
            pending_rows = []

    if pending_rows:
        _flush_batch(db, dataset, dataset_id, pending_rows, counters, settings.max_reported_errors)

    if counters.rows_accepted == 0:
        db.rollback()
        return IngestionReport(
            dataset_id=None,
            filename=filename,
            rows_total=counters.rows_total,
            rows_accepted=0,
            rows_rejected=counters.rows_rejected,
            errors=counters.errors,
            errors_truncated=counters.errors_truncated,
        )

    dataset.row_count_total = counters.rows_total
    dataset.row_count_accepted = counters.rows_accepted
    dataset.row_count_rejected = counters.rows_rejected
    db.add(dataset)
    db.commit()

    return IngestionReport(
        dataset_id=dataset_id,
        filename=filename,
        rows_total=counters.rows_total,
        rows_accepted=counters.rows_accepted,
        rows_rejected=counters.rows_rejected,
        errors=counters.errors,
        errors_truncated=counters.errors_truncated,
    )


def _flush_batch(
    db: Session,
    dataset: Dataset,
    dataset_id: uuid.UUID,
    pending_rows: list[tuple[int, ParsedRow]],
    counters: _Counters,
    max_reported_errors: int,
) -> None:
    """Persist one batch of already-validated rows.

    On success, ``counters.rows_accepted`` grows by the batch size. On
    failure, the batch is rolled back and every row in it is instead counted
    as rejected — earlier, already-committed batches are unaffected.
    """
    items = [
        FeedbackItem(
            dataset_id=dataset_id,
            feedback_text=parsed.feedback_text,
            submitted_at=parsed.submitted_at,
            source=parsed.source,
            customer_id=parsed.customer_id,
            row_number=row_number,
        )
        for row_number, parsed in pending_rows
    ]
    db.add(dataset)
    db.add_all(items)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        db.add(dataset)  # the dataset row may have been pending (uncommitted); re-stage it
        for row_number, _parsed in pending_rows:
            counters.rows_rejected += 1
            reason = f"failed to persist row: {exc}"
            _record_error(counters, max_reported_errors, row_number, None, reason)
        return

    counters.rows_accepted += len(pending_rows)


def _record_error(
    counters: _Counters,
    max_reported_errors: int,
    row_number: int,
    column: str | None,
    reason: str,
) -> None:
    if len(counters.errors) < max_reported_errors:
        counters.errors.append(IngestionError(row_number=row_number, column=column, reason=reason))
    else:
        counters.errors_truncated = True
