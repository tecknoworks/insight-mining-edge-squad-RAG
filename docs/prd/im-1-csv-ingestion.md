# IM-1 — CSV ingestion endpoint + validation

**Type:** Story **Epic:** Ingestion **Priority:** P0 — blocks everything
**Estimate:** 8 points **Depends on:** —
**Branch:** `feat/server/csv-ingestion-endpoint`

## Context

The skeleton boots but stores nothing. `server/app/ingestion/` and `server/app/api/ingestion.py`
are documented stubs, there are no ORM models, and `server/alembic/versions/` is empty. This
ticket lays the foundation the entire pipeline reads from: the first tables, the first migration,
and the endpoint that turns an uploaded CSV into rows in Postgres.

## Goal

A user uploads a CSV of customer feedback through an HTTP endpoint. Every row is parsed,
validated, and persisted. The response tells the caller exactly how many rows were accepted, how
many were rejected, and why each rejection happened — without failing the whole upload because of
a handful of bad rows.

## Scope

**In scope**

- `datasets` and `feedback_items` tables + the first Alembic migration (which also enables the
  `vector` extension so later tickets don't have to).
- CSV parsing, validation, normalisation, and persistence in `app/ingestion/`.
- Upload, list, and detail endpoints in `app/api/ingestion.py`.
- Regenerated typed API client in `client/src/api/`.

**Out of scope**

- Any UI for uploading (a later frontend ticket; verify with `curl` / the OpenAPI docs page).
- Embedding, clustering, or summarisation — those are IM-2/3/4.
- Auth or tenant scoping — that is IM-7. Design the schema so IM-7 can add a nullable
  `organization_id` FK without rewriting these tables.

## Data contract

Per `README.md`. Column matching is **case-insensitive and whitespace-trimmed** on the header row.

| Column          | Required | Type                   | Notes                                                                                                                     |
| --------------- | -------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `feedback_text` | Yes      | text                   | Rejected if missing, empty, or whitespace-only                                                                            |
| `date`          | No       | timestamptz (nullable) | Accept ISO-8601 (`2026-03-14`, `2026-03-14T09:00:00Z`) and `MM/DD/YYYY`. Unparseable → row rejected, do not silently null |
| `source`        | No       | text (nullable)        | Free text, trimmed. e.g. "support ticket", "app review", "survey"                                                         |
| `customer_id`   | No       | text (nullable)        | Trimmed                                                                                                                   |

Unknown extra columns are ignored, not an error. `source`, `date`, and `customer_id` must survive
untouched into `feedback_items` — downstream filtering and temporal analysis depend on them.

## Technical approach

- **Models** (`app/models/`) — SQLAlchemy 2.0 declarative models on the existing `Base` from
  `app/core/db.py`, plus the Pydantic request/response schemas. Keep ORM models and API schemas in
  separate modules (e.g. `app/models/db.py` and `app/models/schemas.py`) so the OpenAPI surface
  never leaks ORM internals.
  - `datasets`: `id` (UUID pk), `filename`, `status` (enum: `ingested`, later `embedded`,
    `clustered`, `summarized`), `row_count_total`, `row_count_accepted`, `row_count_rejected`,
    `created_at`.
  - `feedback_items`: `id` (UUID pk), `dataset_id` (FK → datasets, `ON DELETE CASCADE`, indexed),
    `feedback_text` (text, not null), `submitted_at` (timestamptz, nullable, indexed),
    `source` (text, nullable, indexed), `customer_id` (text, nullable), `row_number` (int — the
    1-based source-CSV line, for traceability), `created_at`.
- **Migration** — `uv run alembic revision --autogenerate`. The migration must begin with
  `CREATE EXTENSION IF NOT EXISTS vector;` so IM-2 can add a `vector` column without a second
  extension step. Confirm `server/alembic/env.py` imports the models' metadata; wire it if not.
- **Parsing** (`app/ingestion/`) — stdlib `csv` over a text stream. Do **not** load the file fully
  into memory and do **not** add pandas for this. Handle a UTF-8 BOM (`utf-8-sig`). Persist in
  batches (~1000 rows) inside a single transaction.
- **Route** (`app/api/ingestion.py`) — thin. Accepts the upload, calls the ingestion module,
  returns the report. No parsing logic in the handler.

## API contract

```
POST /ingestion/uploads
  Content-Type: multipart/form-data
  Body: file=<csv>
  → 201 IngestionReport
  → 400  file is not CSV / header row missing the required `feedback_text` column /
         zero valid rows
  → 413  file exceeds MAX_UPLOAD_BYTES

GET /ingestion/datasets            → 200 list[DatasetSummary]  (newest first, paginated)
GET /ingestion/datasets/{id}       → 200 DatasetDetail | 404
```

`IngestionReport`:

```jsonc
{
  "dataset_id": "uuid",
  "filename": "feedback-q1.csv",
  "rows_total": 1500,
  "rows_accepted": 1487,
  "rows_rejected": 13,
  "errors": [
    // capped at MAX_REPORTED_ERRORS (100)
    { "row_number": 42, "column": "feedback_text", "reason": "value is empty" },
    { "row_number": 97, "column": "date", "reason": "unparseable date: 'last tuesday'" },
  ],
  "errors_truncated": false,
}
```

## New configuration

Add to `app/core/config.py` **and** `server/.env.example` (with these defaults):

- `MAX_UPLOAD_BYTES` = `52428800` (50 MB)
- `MAX_ROWS_PER_UPLOAD` = `100000`
- `MAX_REPORTED_ERRORS` = `100`

## Acceptance criteria

1. `POST /ingestion/uploads` with a well-formed CSV returns **201** and persists one
   `feedback_items` row per accepted CSV row, linked to one new `datasets` row.
2. A row whose `feedback_text` is missing, empty, or whitespace-only is **rejected**; the rest of
   the file still ingests. The report names the row number and the reason.
3. A row with an unparseable `date` is **rejected** with a reason naming the offending value. It is
   not silently stored as `NULL`.
4. `date`, `source`, and `customer_id` are persisted when present and stored as `NULL` when the
   cell is absent or blank. Values round-trip unchanged through `GET /ingestion/datasets/{id}`.
5. A CSV whose header row lacks `feedback_text` (any case) returns **400** and persists **nothing**
   — no partial `datasets` row.
6. A CSV where every row is invalid returns **400** and persists nothing.
7. Header matching is case-insensitive and whitespace-tolerant: `Feedback_Text`, `feedback_text`,
   and `FEEDBACK_TEXT` all resolve to the same column.
8. A UTF-8 file with a BOM ingests correctly — the first header cell is not `﻿feedback_text`.
9. Quoted fields containing commas, embedded newlines, and escaped double-quotes ingest as a single
   correct value.
10. A file over `MAX_UPLOAD_BYTES` returns **413** before the body is fully buffered into memory.
11. A file over `MAX_ROWS_PER_UPLOAD` returns **400** with a message naming the limit.
12. `errors` is capped at `MAX_REPORTED_ERRORS` entries and `errors_truncated` is `true` when the
    cap is hit. `rows_rejected` still reports the true total.
13. `GET /ingestion/datasets` returns datasets newest-first with accurate counts.
14. `GET /ingestion/datasets/{id}` returns **404** for an unknown UUID and **422** for a malformed
    one.
15. `uv run alembic upgrade head` then `uv run alembic downgrade -1` runs clean on an empty
    database. The upgrade creates the `vector` extension.
16. No parsing, validation, or persistence logic lives in `app/api/ingestion.py`.
17. `client/src/api/` is regenerated and committed; `pnpm --filter client build` passes.

## Test plan

- Unit (`server/tests/test_ingestion.py`), against fixture CSVs in `server/tests/fixtures/`:
  happy path; missing required column; empty/whitespace `feedback_text`; bad date; every optional
  column absent; BOM; quoted commas; embedded newlines; row-limit exceeded; all-rows-invalid.
- Integration (`server/tests/test_api_ingestion.py`) via `httpx` + FastAPI `TestClient`: full upload
  → list → detail round-trip asserting counts and that optional fields survive.
- Migration: `alembic upgrade head` → `downgrade -1` → `upgrade head` against a scratch database.
- Manual: `bash .claude/skills/check-setup/check-setup.sh`, then upload via
  `http://localhost:8000/docs`.

## Definition of done

Spec signed off → implemented → `ruff`, `mypy --strict`, `pytest` green → `pnpm generate:api` run
and the diff committed → `pnpm --filter client build` green → PR opened with `/git-pr` and
squash-merged.
