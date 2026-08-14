"""CSV header mapping and per-row validation.

Matches the data contract in ``docs/prd/im-1-csv-ingestion.md``: only
``feedback_text`` is required; ``date``, ``source``, and ``customer_id`` are
optional and must survive into ``feedback_items`` unchanged where present.
Column matching is case-insensitive, whitespace-tolerant, and
order-independent; unknown extra columns are ignored.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

FEEDBACK_TEXT_COLUMN = "feedback_text"
DATE_COLUMN = "date"
SOURCE_COLUMN = "source"
CUSTOMER_ID_COLUMN = "customer_id"

_KNOWN_COLUMNS = {FEEDBACK_TEXT_COLUMN, DATE_COLUMN, SOURCE_COLUMN, CUSTOMER_ID_COLUMN}
_MM_DD_YYYY = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def normalize_header(name: str) -> str:
    """Normalize a header cell for case/whitespace-insensitive matching."""
    return re.sub(r"\s+", "_", name.strip().lower())


def build_column_map(header_row: list[str]) -> dict[str, int]:
    """Map known column names to their index in ``header_row``.

    Matching is case-insensitive and whitespace-tolerant; unknown columns are
    ignored. If a known column name appears more than once, the first
    occurrence wins.
    """
    column_map: dict[str, int] = {}
    for index, raw_name in enumerate(header_row):
        normalized = normalize_header(raw_name)
        if normalized in _KNOWN_COLUMNS and normalized not in column_map:
            column_map[normalized] = index
    return column_map


@dataclass
class ParsedRow:
    """A validated, ready-to-persist CSV data row."""

    feedback_text: str
    submitted_at: datetime | None
    source: str | None
    customer_id: str | None


@dataclass
class RowError:
    """Why a CSV data row was rejected."""

    column: str
    reason: str


def parse_date(raw_value: str) -> datetime:
    """Parse an ISO-8601 or ``MM/DD/YYYY`` date string as naive UTC.

    Raises ``ValueError`` if the value matches neither format.
    """
    candidate = raw_value.strip()
    iso_candidate = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        pass
    else:
        return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed

    if _MM_DD_YYYY.match(candidate):
        month_str, day_str, year_str = candidate.split("/")
        try:
            return datetime(int(year_str), int(month_str), int(day_str))
        except ValueError:
            pass

    raise ValueError(f"unparseable date: {candidate!r}")


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _cell(cells: list[str], column_map: dict[str, int], column: str) -> str | None:
    index = column_map.get(column)
    if index is None or index >= len(cells):
        return None
    return cells[index]


def parse_row(
    cells: list[str], column_map: dict[str, int]
) -> tuple[ParsedRow | None, RowError | None]:
    """Validate one CSV data row.

    Returns either a ``ParsedRow`` (valid) or a ``RowError`` (rejected) —
    never both.
    """
    feedback_text = (_cell(cells, column_map, FEEDBACK_TEXT_COLUMN) or "").strip()
    if not feedback_text:
        return None, RowError(column=FEEDBACK_TEXT_COLUMN, reason="value is empty")

    submitted_at: datetime | None = None
    date_raw = _cell(cells, column_map, DATE_COLUMN)
    if date_raw is not None and date_raw.strip():
        try:
            submitted_at = parse_date(date_raw)
        except ValueError as exc:
            return None, RowError(column=DATE_COLUMN, reason=str(exc))

    source = _clean_optional(_cell(cells, column_map, SOURCE_COLUMN))
    customer_id = _clean_optional(_cell(cells, column_map, CUSTOMER_ID_COLUMN))

    return (
        ParsedRow(
            feedback_text=feedback_text,
            submitted_at=submitted_at,
            source=source,
            customer_id=customer_id,
        ),
        None,
    )
