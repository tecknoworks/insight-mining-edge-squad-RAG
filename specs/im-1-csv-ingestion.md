# Feature: CSV ingestion endpoint + validation

`IM-1` · Epic: Ingestion · Branch: `feat/server/csv-ingestion-endpoint` · Source PRD: `docs/prd/im-1-csv-ingestion.md`

## Goal

The skeleton currently persists nothing. This spec lays the pipeline's foundation: the first two
tables (`datasets`, `feedback_items`), the first Alembic migration, and an HTTP endpoint that turns
an uploaded CSV of customer feedback into rows in SQLite. Every row is parsed, validated, and
persisted independently — a handful of bad rows reject individually with a reason instead of
failing the whole upload. Large files are split into internal batches automatically; there is no
user-facing size or row-count limit. This is the entry point every later pipeline stage
(embeddings, clustering, summarization) reads from.

## Acceptance Criteria

1. `POST /ingestion/uploads` with a well-formed CSV returns **201** and persists one
   `feedback_items` row per accepted CSV row, linked to one new `datasets` row.
2. A row whose `feedback_text` is missing, empty, or whitespace-only is **rejected**; the rest of
   the file still ingests. The report names the row number and the reason.
3. A row with an unparseable `date` is **rejected** with a reason naming the offending value — it
   is never silently stored as `NULL`.
4. `date`, `source`, and `customer_id` are persisted when present and stored as `NULL` when the
   cell is absent or blank. Values round-trip unchanged through `GET /ingestion/datasets/{id}`.
5. A CSV whose header row lacks `feedback_text` (any case/whitespace variant) returns **400** and
   persists **nothing** — no partial `datasets` row.
6. A CSV where every data row is invalid returns **400** and persists nothing.
7. Header matching is case-insensitive, whitespace-tolerant, and order-independent
   (`Feedback_Text`, `FEEDBACK_TEXT`, `feedback text` all resolve to the same column; columns may
   appear in any order). Unknown extra columns are ignored, not an error.
8. A UTF-8 file with a BOM ingests correctly — the first header cell is not `﻿feedback_text`.
9. Quoted fields containing commas, embedded newlines, and escaped double-quotes ingest as a
   single correct value.
10. A very large file (1M+ rows) is accepted and batched internally, committing every
    `INTERNAL_BATCH_SIZE` rows. If one batch fails, prior committed batches remain persisted and
    the response reflects partial success with accurate `rows_accepted` / `rows_rejected` counts.
11. `errors` in the response is capped at `MAX_REPORTED_ERRORS` entries and `errors_truncated` is
    `true` when the cap is hit; `rows_rejected` still reports the true total regardless of the cap.
12. `GET /ingestion/datasets` returns datasets newest-first with accurate row counts, paginated.
13. `GET /ingestion/datasets/{id}` returns **404** for a well-formed but unknown UUID and **422**
    for a malformed one.
14. `uv run alembic upgrade head` then `uv run alembic downgrade -1` both run clean against an
    empty database.
15. No parsing, validation, or persistence logic lives in `app/api/ingestion.py` — it only calls
    into `app/ingestion/` and returns the result.
16. `client/src/api/` is regenerated from the new OpenAPI schema and committed; `pnpm --filter
client build` passes.

## Technical Approach

- **Models** — new `app/models/db.py` (SQLAlchemy 2.0 declarative ORM, subclassing the existing
  `Base` from `app/core/db.py`) and `app/models/schemas.py` (Pydantic request/response models).
  Kept in separate modules so the OpenAPI surface never leaks ORM internals.
  - `Dataset` (`datasets` table): `id` (UUID pk), `filename` (str), `status` (enum:
    `ingested`, `embedded`, `clustered`, `summarized` — only `ingested` is set by this ticket),
    `row_count_total`, `row_count_accepted`, `row_count_rejected` (int), `created_at` (timestamptz).
  - `FeedbackItem` (`feedback_items` table): `id` (UUID pk), `dataset_id` (FK → `datasets.id`,
    `ON DELETE CASCADE`, indexed), `feedback_text` (text, not null), `submitted_at` (timestamptz,
    nullable, indexed — maps from the CSV `date` column), `source` (text, nullable, indexed),
    `customer_id` (text, nullable), `row_number` (int, not null — 1-based source-CSV data-row
    number, for traceability), `created_at` (timestamptz).
  - Schema is designed so IM-7 can later add a nullable `organization_id` FK to both tables
    without a rewrite; no auth/tenant scoping is implemented here.
- **Migration** — `uv run alembic revision --autogenerate -m "add datasets and feedback_items"`.
  Add `from app import models  # noqa: F401` (or equivalent) to `alembic/env.py` so autogenerate
  and future runs see the models' metadata.
  - **Note on the source PRD's "enable the `vector` extension" line:** this repo runs on SQLite
    with an in-memory `hnswlib` index for vector search (per `CLAUDE.md`), not a Postgres `vector`
    extension. That line does not apply here and is intentionally **not** carried into this
    migration; embeddings/vector storage is IM-2/3's concern, not this ticket's.
- **Parsing & persistence** (`app/ingestion/`) — new module(s), e.g. `app/ingestion/parser.py`
  (CSV → validated row / error) and `app/ingestion/service.py` (orchestrates parse → batch
  persist → build report):
  - Use the stdlib `csv` module over a text stream (`io.TextIOWrapper` on the upload's file
    object) — never load the full file into memory, never add pandas.
  - Decode with `utf-8-sig` so a BOM on the first header cell is stripped automatically.
  - Read the header row first; build a case-insensitive, whitespace-trimmed column-name → index
    map. If `feedback_text` isn't found in the map, stop immediately: return a 400 report, persist
    no `datasets` row, and never open a DB transaction.
  - Stream data rows, validating each independently:
    - `feedback_text`: reject if missing/empty/whitespace-only.
    - `date` → `submitted_at`: try ISO-8601 first (`datetime.fromisoformat`, handling a bare
      `Z` suffix), then `MM/DD/YYYY`; reject with the offending raw value if both fail. A
      blank/whitespace-only cell is `None`, not a rejection.
      **Suggested new module**: none — keep the date parsing as a small helper in the ingestion
      module.
    - `source`, `customer_id`: trim; whitespace-only → `NULL`.
  - Accumulate valid rows into batches of `settings.internal_batch_size` (default 1000) and
    `session.add_all()` + `commit()` per batch, so a failure partway through a huge file still
    leaves prior batches durable. Track `rows_total` / `rows_accepted` / `rows_rejected` as
    running counters, independent of the capped `errors` list.
  - Cap the returned `errors` list at `settings.max_reported_errors` (default 100); once hit, keep
    counting `rows_rejected` but stop appending to `errors` and set `errors_truncated = True`.
  - After the stream ends: if `rows_accepted == 0`, return 400 and roll back / discard the
    `datasets` row created for this upload (no partial dataset row persists). Otherwise create/
    finalize the `Dataset` row with `status="ingested"` and the final counts, and return 201.
- **Route** (`app/api/ingestion.py`) — thin handlers only:
  - `POST /ingestion/uploads` — accepts `UploadFile`, calls the ingestion service, maps its
    result to `IngestionReport` + status code (201 or 400). No parsing/validation logic here.
  - `GET /ingestion/datasets` — paginated list, newest-first (`ORDER BY created_at DESC`), maps
    to `list[DatasetSummary]`.
  - `GET /ingestion/datasets/{id}` — `id: uuid.UUID` path param (FastAPI/Pydantic gives 422 for a
    malformed UUID automatically); 404 via `HTTPException` when no row matches; else
    `DatasetDetail`.
- **Config** (`app/core/config.py` + `server/.env.example`) — add:
  - `internal_batch_size: int = 1000` / `INTERNAL_BATCH_SIZE=1000`
  - `max_reported_errors: int = 100` / `MAX_REPORTED_ERRORS=100`
- **Dependency**: FastAPI's `UploadFile` (multipart parsing) requires `python-multipart` at
  runtime — add it to `server/pyproject.toml` dependencies (not currently present) and run
  `uv sync`.
- **Frontend**: after the backend routes/schemas land and the server boots, run
  `pnpm --filter client generate:api` and commit the resulting diff under `client/src/api/`. No
  UI work in this ticket (upload is verified via `/docs` or `curl`).

## Edge Cases / Constraints

- Header present but empty file (zero data rows) → `rows_total = 0`, `rows_accepted = 0` → 400,
  same as "every row invalid."
- A CSV with only a header row and no trailing newline still parses correctly (stdlib `csv`
  handles this).
- Duplicate header columns matching `feedback_text` case-insensitively (e.g. both `Feedback_Text`
  and `feedback_text` present) — use the first match; not required to error, but must not crash.
- `row_number` in the report and in `feedback_items` is the 1-based position among **data** rows
  (header excluded), matching what a user would count opening the CSV in a spreadsheet minus the
  header.
- A batch commit failing mid-stream (e.g. a DB constraint error unrelated to per-row validation)
  must not lose previously committed batches — each batch's `session.commit()` stands on its own;
  only the failing batch's rows are affected, and remaining valid rows in that batch still count
  toward `rows_rejected` with a reason.
- No file-size or row-count ceiling is enforced anywhere in this ticket (explicit PRD requirement)
  — do not add one "for safety."
- SQLite has no native `timestamptz`; store `submitted_at`/`created_at` as UTC-naive
  `DateTime`/ISO strings via SQLAlchemy's `DateTime` type and treat all input dates as UTC when
  parsed (no timezone-offset column needed at this stage).

## Files to Modify

- `server/app/models/db.py` (create) — `Dataset`, `FeedbackItem` ORM models.
- `server/app/models/schemas.py` (create) — `IngestionReport`, `IngestionError`,
  `DatasetSummary`, `DatasetDetail` Pydantic schemas.
- `server/app/models/__init__.py` (modify) — export/import the new modules so Alembic autogenerate
  and the app both see them.
- `server/app/ingestion/parser.py` (create) — header mapping, per-row validation, date parsing.
- `server/app/ingestion/service.py` (create) — batch orchestration, report assembly.
- `server/app/ingestion/__init__.py` (modify) — update the module docstring; no logic here.
- `server/app/api/ingestion.py` (modify) — implement the three routes; stays thin.
- `server/app/core/config.py` (modify) — add `internal_batch_size`, `max_reported_errors`.
- `server/.env.example` (modify) — document the two new env vars with their defaults.
- `server/alembic/env.py` (modify) — import the models module for autogenerate.
- `server/alembic/versions/xxxx_add_datasets_and_feedback_items.py` (create, via autogenerate) —
  first migration.
- `server/pyproject.toml` (modify) — add `python-multipart` dependency.
- `server/tests/test_ingestion.py` (create) — unit tests against fixture CSVs.
- `server/tests/test_api_ingestion.py` (create) — integration tests via `TestClient`.
- `server/tests/fixtures/*.csv` (create) — happy path, missing required column, empty/whitespace
  `feedback_text`, bad date, all-optional-columns-absent, BOM, quoted commas, embedded newlines,
  all-rows-invalid.
- `client/src/api/**` (regenerate, commit the diff) — via `pnpm --filter client generate:api`.

## Test Plan

- **Unit** (`server/tests/test_ingestion.py`) against `server/tests/fixtures/`: happy path;
  missing required column (any case); empty/whitespace `feedback_text`; unparseable `date`; every
  optional column absent; UTF-8 BOM; quoted commas; embedded newlines; all-rows-invalid.
- **Integration** (`server/tests/test_api_ingestion.py`) via `httpx` + FastAPI `TestClient`: full
  upload → list → detail round-trip, asserting counts and that `date`/`source`/`customer_id`
  survive unchanged; 404 on unknown UUID; 422 on malformed UUID; 400 + zero persistence on
  missing-required-column and all-rows-invalid cases.
- **Migration**: `uv run alembic upgrade head` → `uv run alembic downgrade -1` → `upgrade head`
  again against a scratch database.
- **Manual**: `bash .claude/skills/check-setup/check-setup.sh`, then upload a sample CSV via
  `http://localhost:8000/docs`.
- **Definition of done**: spec signed off → implemented → `ruff`, `mypy --strict`, `pytest` all
  green → `pnpm generate:api` run and its diff committed → `pnpm --filter client build` green →
  PR opened with `/git-pr` and squash-merged.
