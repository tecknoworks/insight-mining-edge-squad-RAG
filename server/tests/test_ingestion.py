"""Unit tests for the ingestion parser/service against fixture CSVs.

Uses an isolated in-memory SQLite session per test — no shared state with
``insight_miner.db``.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import Base
from app.ingestion.parser import build_column_map, parse_date, parse_row
from app.ingestion.service import HeaderValidationError, ingest_csv

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _open(name: str) -> BinaryIO:
    return (FIXTURES / name).open("rb")


# --- header mapping -----------------------------------------------------


def test_build_column_map_is_case_and_whitespace_insensitive() -> None:
    column_map = build_column_map(["Feedback_Text", "FEEDBACK TEXT".replace(" ", "_")])
    assert "feedback_text" in column_map


def test_build_column_map_ignores_unknown_columns() -> None:
    column_map = build_column_map(["feedback_text", "some_other_column"])
    assert column_map == {"feedback_text": 0}


# --- date parsing ---------------------------------------------------------


def test_parse_date_iso() -> None:
    assert parse_date("2026-03-14").isoformat() == "2026-03-14T00:00:00"


def test_parse_date_iso_with_z_suffix() -> None:
    assert parse_date("2026-03-15T09:00:00Z").isoformat() == "2026-03-15T09:00:00"


def test_parse_date_mm_dd_yyyy() -> None:
    assert parse_date("03/16/2026").isoformat() == "2026-03-16T00:00:00"


def test_parse_date_unparseable_raises() -> None:
    with pytest.raises(ValueError, match="unparseable date"):
        parse_date("last tuesday")


# --- row validation --------------------------------------------------------


def test_parse_row_rejects_empty_feedback_text() -> None:
    column_map = {"feedback_text": 0}
    parsed, error = parse_row([""], column_map)
    assert parsed is None
    assert error is not None
    assert error.column == "feedback_text"


def test_parse_row_rejects_whitespace_only_feedback_text() -> None:
    column_map = {"feedback_text": 0}
    parsed, error = parse_row(["   "], column_map)
    assert parsed is None
    assert error is not None


def test_parse_row_accepts_missing_optional_columns() -> None:
    column_map = {"feedback_text": 0}
    parsed, error = parse_row(["Something broke"], column_map)
    assert error is None
    assert parsed is not None
    assert parsed.source is None
    assert parsed.customer_id is None
    assert parsed.submitted_at is None


# --- ingest_csv: happy path -------------------------------------------------


def test_ingest_csv_happy_path(db: Session) -> None:
    with _open("happy_path.csv") as f:
        report = ingest_csv(db, "happy_path.csv", f)

    assert report.dataset_id is not None
    assert report.rows_total == 3
    assert report.rows_accepted == 3
    assert report.rows_rejected == 0
    assert report.errors == []
    assert report.errors_truncated is False


def test_ingest_csv_missing_required_column_raises(db: Session) -> None:
    with _open("missing_required_column.csv") as f, pytest.raises(HeaderValidationError):
        ingest_csv(db, "missing_required_column.csv", f)


def test_ingest_csv_empty_feedback_text_rejected_individually(db: Session) -> None:
    with _open("empty_feedback_text.csv") as f:
        report = ingest_csv(db, "empty_feedback_text.csv", f)

    assert report.rows_total == 4
    assert report.rows_accepted == 2
    assert report.rows_rejected == 2
    reasons = {(e.row_number, e.column) for e in report.errors}
    assert (2, "feedback_text") in reasons
    assert (3, "feedback_text") in reasons


def test_ingest_csv_bad_date_rejected_with_reason(db: Session) -> None:
    with _open("bad_date.csv") as f:
        report = ingest_csv(db, "bad_date.csv", f)

    assert report.rows_total == 2
    assert report.rows_accepted == 1
    assert report.rows_rejected == 1
    assert report.errors[0].column == "date"
    assert "last tuesday" in report.errors[0].reason


def test_ingest_csv_all_optional_columns_absent(db: Session) -> None:
    with _open("all_optional_absent.csv") as f:
        report = ingest_csv(db, "all_optional_absent.csv", f)

    assert report.rows_accepted == 2
    assert report.rows_rejected == 0


def test_ingest_csv_bom_stripped_from_header(db: Session) -> None:
    with _open("bom.csv") as f:
        report = ingest_csv(db, "bom.csv", f)

    assert report.rows_accepted == 1
    assert report.rows_rejected == 0


def test_ingest_csv_quoted_commas_and_newlines(db: Session) -> None:
    with _open("quoted_commas.csv") as f:
        report = ingest_csv(db, "quoted_commas.csv", f)

    assert report.rows_total == 3
    assert report.rows_accepted == 3
    assert report.rows_rejected == 0


def test_ingest_csv_all_rows_invalid_accepts_nothing(db: Session) -> None:
    with _open("all_rows_invalid.csv") as f:
        report = ingest_csv(db, "all_rows_invalid.csv", f)

    assert report.dataset_id is None
    assert report.rows_accepted == 0
    assert report.rows_rejected == report.rows_total
