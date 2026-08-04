# IM-1 — CSV ingestion endpoint + validation

**Type:** Story **Epic:** Ingestion **Priority:** P0 — blocks everything
**Estimate:** 8 points **Depends on:** —
**Branch:** `feat/server/csv-ingestion-endpoint`

## Context

The skeleton boots but stores nothing. `server/app/ingestion/` and `server/app/api/ingestion.py`
are documented stubs, there are no ORM models, and `server/alembic/versions/` is empty. This
ticket lays the foundation the entire pipeline reads from: the first tables, the first migration,
and the endpoint that turns an uploaded CSV into rows in SQLite. **Large uploads are automatically
split into internal batches** — no artificial limits on file size or row count.

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

Per `README.md`. Column matching is **by header name, case-insensitive, whitespace-trimmed** (order
does not matter). Parsing reads the header row, normalizes column names, then processes data rows.

| Column          | Required | Type                   | Notes                                                                                                                                                |
| --------------- | -------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `feedback_text` | Yes      | text                   | Rejected if missing, empty, or whitespace-only. Column name match: `feedback_text`, `Feedback_Text`, `FEEDBACK TEXT` all resolve to the same column. |
| `date`          | No       | timestamptz (nullable) | Accept ISO-8601 (`2026-03-14`, `2026-03-14T09:00:00Z`) and `MM/DD/YYYY`. Unparseable → row rejected, do not silently null                            |
| `source`        | No       | text (nullable)        | Free text, trimmed. e.g. "support ticket", "app review", "survey". Whitespace-only cells become `NULL`.                                              |
| `customer_id`   | No       | text (nullable)        | Trimmed. Whitespace-only cells become `NULL`.                                                                                                        |

**Column order does not matter.** The parser reads the header row, maps column names (case-insensitive),
and processes each data row by matched column position. Unknown extra columns are ignored, not an error.
`source`, `date`, and `customer_id` must survive untouched into `feedback_items` — downstream filtering
and temporal analysis depend on them.

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
- **Migration** — `uv run alembic revision --autogenerate`. Confirm `server/alembic/env.py`
  imports the models' metadata; wire it if not.
- **Parsing** (`app/ingestion/`) — stdlib `csv` over a text stream. Do **not** load the file fully
  into memory and do **not** add pandas for this. Handle a UTF-8 BOM (`utf-8-sig`). **Persist in
  batches** of `INTERNAL_BATCH_SIZE` rows (default ~1000), committing each batch separately so large
  uploads succeed even if one batch fails. There is no user-facing file size or row limit; the
  endpoint streams the input and splits it internally.
- **Route** (`app/api/ingestion.py`) — thin. Accepts the upload, calls the ingestion module,
  returns the report. No parsing logic in the handler.

## API contract

```
POST /ingestion/uploads
  Content-Type: multipart/form-data
  Body: file=<csv>
  → 201 IngestionReport (even for very large files; batched internally)
  → 400  file is not CSV / header row missing the required `feedback_text` column /
         zero valid rows

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

- `INTERNAL_BATCH_SIZE` = `1000` (rows committed per transaction; no upload limit)
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
7. Header matching is case-insensitive, whitespace-tolerant, and order-independent:
   `Feedback_Text`, `feedback_text`, `FEEDBACK_TEXT`, `feedback text` (with space) all resolve to
   the same column. A CSV with columns in any order (e.g., `customer_id`, `date`, `feedback_text`)
   ingests correctly.
8. A UTF-8 file with a BOM ingests correctly — the first header cell is not `﻿feedback_text`.
9. Quoted fields containing commas, embedded newlines, and escaped double-quotes ingest as a single
   correct value.
10. A very large file (1M+ rows) is accepted and batched internally, committing every `INTERNAL_BATCH_SIZE`
    rows. If one batch fails, prior batches are persisted and the response indicates partial success
    with accurate `rows_accepted` and `rows_rejected` counts.
11. `errors` is capped at `MAX_REPORTED_ERRORS` entries and `errors_truncated` is `true` when the
    cap is hit. `rows_rejected` still reports the true total.
12. `GET /ingestion/datasets` returns datasets newest-first with accurate counts.
13. `GET /ingestion/datasets/{id}` returns **404** for an unknown UUID and **422** for a malformed
    one.
14. `uv run alembic upgrade head` then `uv run alembic downgrade -1` runs clean on an empty
    database.
15. No parsing, validation, or persistence logic lives in `app/api/ingestion.py`.
16. `client/src/api/` is regenerated and committed; `pnpm --filter client build` passes.

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
