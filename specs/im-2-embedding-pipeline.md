# Feature: Embedding pipeline

`IM-2` · Epic: Embeddings · Branch: `feat/server/embedding-pipeline` · Source PRD:
`docs/prd/im-2-embedding-pipeline.md` · Depends on: IM-1

## Goal

Semantic clustering (IM-3) and chat-with-data (IM-6) read vectors, not text. This spec turns every
`feedback_items` row lacking an embedding into a vector, using **open-source `sentence-transformers`
models running locally** — zero per-embedding API cost, trading it for local CPU inference. Vectors
are stored in a new `feedback_items.embedding` BLOB column and indexed in an in-memory `hnswlib`
HNSW graph (cosine distance) for fast similarity search. The endpoint is idempotent and
batch-resumable: a re-run only touches rows still missing an embedding, and job progress survives a
process restart because it lives in the database, not memory. There is no background worker/queue
yet — FastAPI `BackgroundTasks` runs the job in-process, with the resulting ceiling documented below.

**Correction carried into this spec:** the scaffold (`c148661`) wired a **Voyage AI** hosted-provider
stub — `voyage_api_key` / `VOYAGE_API_KEY` in `app/core/config.py` / `.env.example`, and the
`app/embeddings/__init__.py` docstring. The cost-reduction decision to use local
`sentence-transformers` instead (see `docs/PRD-FIXES.md` and the project's approved cost strategy)
was never carried into that code. This spec removes the stale Voyage references as part of adding
the real config — it is not an out-of-scope cleanup, it is this ticket's own configuration surface.

## Acceptance Criteria

1. `POST /ingestion/datasets/{id}/embed` populates `feedback_items.embedding` for every item in the
   dataset that had `NULL`, and leaves already-embedded items untouched.
2. Calling the endpoint a second time on a fully embedded dataset returns **202** with
   `items_total: 0`, `items_embedded: 0`, `state: "completed"`, and makes **zero** model inference
   calls (the un-embedded-rows query returns nothing, so the batch loop never runs).
3. `GET /ingestion/datasets/{id}/embed` reports accurate `items_total` / `items_embedded` /
   `items_failed` while the job runs and after it finishes, and survives a server restart mid-job —
   state lives in a DB row (`embedding_jobs`), never in memory.
4. If one batch fails (e.g. simulated OOM), previously committed batches remain embedded, `state`
   becomes `"failed"`, `items_failed` equals that batch's size, and `error` carries a useful message.
   The batch loop stops at the first failure (fail-fast) rather than skipping ahead. A subsequent
   `POST` recomputes `items_total` from the rows still `NULL` and resumes from there.
5. Feedback text exceeding the model's token limit (512 tokens for MiniLM) is truncated
   deterministically at the tokenizer level before encoding, rather than erroring; each truncation is
   logged with the feedback item's id.
6. The stored vector's length equals `settings.embedding_dimension` for every embedded row; a
   configured `EMBEDDING_DIMENSION` that doesn't match the model's actual output dimension fails
   fast at startup (client construction), not silently per-row.
7. The in-memory HNSW index is (re)built from every row with a non-`NULL` embedding on app startup
   and at the end of every embed job (success or failure) — index size equals the number of embedded
   rows in the database at that point.
8. A similarity search against the HNSW index returns neighbors ordered by cosine distance
   (ascending); this is exercised directly against `app/embeddings/index.py` in tests (no search
   endpoint is added — IM-6 owns that).
9. `POST` on an unknown dataset id returns **404**; `POST` while a job for that dataset is already
   `pending`/`running` returns **409**.
10. `uv run alembic upgrade head` then `uv run alembic downgrade -1` both run clean against a
    database already populated by IM-1 fixtures (nullable column + new table only — no data loss).
11. **The model ID appears nowhere in application code** — only as a `settings.embedding_model` /
    `settings.embedding_dimension` read, sourced from `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION`.
12. No embedding, batching, or index logic lives in `app/api/ingestion.py` — the two routes only
    call into `app/embeddings/` and translate the result to a status code.
13. `voyage_api_key` / `VOYAGE_API_KEY` are removed from `app/core/config.py` and `.env.example`; the
    `app/embeddings/__init__.py` docstring no longer references Voyage AI.
14. `client/src/api/` is regenerated from the new OpenAPI schema and committed; `pnpm --filter
client build` passes.

## Technical Approach

- **Config** (`app/core/config.py` + `server/.env.example`) — remove `voyage_api_key` /
  `VOYAGE_API_KEY` (see Goal). Add:
  - `embedding_model: str = "all-MiniLM-L6-v2"` / `EMBEDDING_MODEL`
  - `embedding_dimension: int = 384` / `EMBEDDING_DIMENSION`
  - `embedding_batch_size: int = 32` / `EMBEDDING_BATCH_SIZE`
- **Models** (`app/models/db.py`):
  - `FeedbackItem.embedding: Mapped[bytes | None]` — new `LargeBinary` (BLOB) column, nullable,
    default `NULL`. Stored as a raw `numpy.float32` array via `.tobytes()`; no header, since the
    dimension is a single global config value, not per-row.
  - New `EmbeddingJob` model, table `embedding_jobs`, **one row per dataset** (`dataset_id` unique,
    `ForeignKey("datasets.id", ondelete="CASCADE")`): `id` (UUID pk), `dataset_id`, `state`
    (`EmbeddingJobState` enum: `pending | running | completed | failed`), `items_total`,
    `items_embedded`, `items_failed` (int, default 0), `model` (str — the `EMBEDDING_MODEL` value at
    job start), `dimension` (int), `error` (text, nullable), `started_at` / `finished_at`
    (`DateTime`, nullable), `created_at`. A `POST` on a dataset with an existing job row **resets**
    that row for the new run rather than inserting a new one — `GET` always reports the latest run.
- **Schemas** (`app/models/schemas.py`) — `EmbeddingJobState` (`StrEnum`, mirrors `DatasetStatus`'s
  pattern) and `EmbeddingJobStatus` (`dataset_id`, `state`, `items_total`, `items_embedded`,
  `items_failed`, `model`, `dimension`, `error`, `started_at`, `finished_at`), `from_attributes=True`.
- **Client** (`app/embeddings/client.py`) — narrow `Protocol`:
  ```python
  class EmbeddingClient(Protocol):
      def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
      def embed_query(self, text: str) -> list[float]: ...
  ```
  `SentenceTransformerEmbeddingClient` wraps a single `sentence_transformers.SentenceTransformer`
  instance (both helpers call the same underlying model — MiniLM has no separate query/document
  mode, matching IM-6's expected interface). On construction, compare
  `model.get_sentence_embedding_dimension()` against `settings.embedding_dimension` and raise
  immediately on mismatch (AC 6). Before encoding, truncate each text at the tokenizer level to the
  model's `max_seq_length`, decode back to a string, and `logging.getLogger(__name__).warning(...)`
  the item when truncation occurred (AC 5). `get_embedding_client()` is an `lru_cache`-wrapped
  factory (same pattern as `get_settings()`), loading the model once per process.
- **Index** (`app/embeddings/index.py`) — a module-level, lazily-built `hnswlib.Index(space="cosine",
dim=settings.embedding_dimension)`. `hnswlib` requires integer labels, not UUIDs, so the module
  keeps a parallel `list[uuid.UUID]` (label → `feedback_item_id`) rebuilt alongside the index.
  - `build_index(db: Session) -> None` — full rebuild: query every `FeedbackItem` with
    `embedding IS NOT NULL`, decode each BLOB back to `float32`, `init_index` +
    `add_items(vectors, labels)`. Rebuilding from scratch (not incremental `add_items` on top of the
    live index) keeps this simple at this data scale; flagged in Edge Cases as a later optimization.
  - `search(query_vector: list[float], k: int) -> list[tuple[uuid.UUID, float]]` — `knn_query`,
    mapped back through the label list, returned ascending by distance. No route calls this yet
    (IM-6's job); it exists so this spec's AC 8 is independently testable.
- **Service** (`app/embeddings/service.py`) — two entry points, both taking an injectable
  `embedding_client: EmbeddingClient = None` (defaults to `get_embedding_client()`) so tests can pass
  a stub with no network/model-download calls:
  - `start_or_resume_job(db, dataset_id) -> EmbeddingJob` — called synchronously from the route.
    404s (via a raised `DatasetNotFoundError`) if the dataset doesn't exist. Raises
    `JobAlreadyRunningError` if the existing job row's `state` is `pending` or `running` (→ 409).
    Otherwise counts `feedback_items` rows `WHERE dataset_id = :id AND embedding IS NULL`, upserts
    the `EmbeddingJob` row with `state="pending"`, that count as `items_total`, zeroed counters,
    `model`/`dimension` from current settings, `started_at=now`, `finished_at=None`, `error=None`,
    and commits.
  - `run_job(dataset_id) -> None` — the `BackgroundTasks` target. **Opens its own `SessionLocal()`**
    and closes it in a `finally` (the request-scoped session from `Depends(get_db)` is not safe to
    reuse here — it may already be torn down by the time the background task runs). Sets
    `state="running"`, commits. Streams un-embedded rows in batches of
    `settings.embedding_batch_size`: for each batch, call `embedding_client.embed_documents(texts)`,
    write each vector's bytes to its row's `embedding` column, `commit()`. On success of all
    batches: `state="completed"`, `finished_at=now`; if the dataset's `status` is still `INGESTED`,
    advance it to `EMBEDDED` (never regress a more-advanced status). On any exception from a batch:
    roll back only that batch, set `items_failed` to that batch's size, `state="failed"`,
    `error=str(exc)`, `finished_at=now`, commit, and **stop** — do not attempt later batches (AC 4).
    In a `finally`, call `build_index()` against the same session so the index reflects whatever got
    embedded, whether the job succeeded or failed (AC 7).
- **Routes** (`app/api/ingestion.py`, extending the existing `/ingestion` router — thin handlers
  only):
  - `POST /ingestion/datasets/{id}/embed` — calls `start_or_resume_job`, maps `DatasetNotFoundError`
    → 404 and `JobAlreadyRunningError` → 409, otherwise
    `background_tasks.add_task(run_job, dataset_id)` and returns the just-created job as
    `EmbeddingJobStatus` with **202**.
  - `GET /ingestion/datasets/{id}/embed` — loads the `EmbeddingJob` row for `dataset_id`; 404 if no
    dataset or no job has ever been started for it; else `EmbeddingJobStatus` with **200**.
- **Startup** (`app/main.py`) — add a `lifespan` (or `@app.on_event("startup")`) hook that opens a
  short-lived `SessionLocal()` and calls `build_index()` once, so the index is warm before the first
  request (AC 7's "on app startup" clause).
- **Migration** — `uv run alembic revision --autogenerate -m "add embeddings"`: adds the nullable
  `feedback_items.embedding` column and the new `embedding_jobs` table. No changes to existing
  `datasets`/`feedback_items` data.
- **Dependencies**: add `sentence-transformers` and `hnswlib` via `uv add` (both pull in `numpy`
  transitively; no need to pin it directly).

## Edge Cases / Constraints

- **`BackgroundTasks` ceiling (explicitly out of scope to fix, per the PRD):** there is no
  heartbeat/lease. If the server process is killed mid-job, the `embedding_jobs` row is stuck at
  `state="running"` forever — no automatic recovery — and every subsequent `POST` for that dataset
  returns 409 indefinitely. A real fix needs a worker/queue (tracked as future work, not this
  ticket); this is a known, documented limitation, not a bug to silently work around here.
- `hnswlib` indices are not resizable/updatable in place the way this spec uses them — every rebuild
  is a fresh `init_index` over all embedded rows. Fine at current data volumes; an incremental index
  is a future optimization, not required here.
- `EMBEDDING_DIMENSION` must match the configured model's real output size. A mismatch is a
  configuration error, not a per-row validation concern — fail at `EmbeddingClient` construction
  (process startup / first use), never store a truncated or padded vector.
- A dataset with zero `feedback_items` (shouldn't happen post-IM-1, since an all-rejected upload
  persists no dataset) still behaves correctly: `items_total = 0`, job completes immediately with
  zero inference calls.
- Batch failure is fail-fast, not best-effort: the batch that raised is the only one counted in
  `items_failed`; batches queued after it are simply never attempted and stay `NULL`, to be picked
  up by `items_total` on the next `POST` — they are not double-counted as failed.
- `feedback_items.embedding` truncation and re-embedding are per-row-independent, like IM-1's
  per-row CSV validation — a truncated-text embedding is still a valid embedding, never a rejection.
- SQLite has no vector type; the BLOB is opaque outside this module — any code needing the vector
  back must know the current `EMBEDDING_DIMENSION` to reinterpret the bytes as `float32`.

## Files to Modify

- `server/app/core/config.py` (modify) — remove `voyage_api_key`; add `embedding_model`,
  `embedding_dimension`, `embedding_batch_size`.
- `server/.env.example` (modify) — remove `VOYAGE_API_KEY`; document the three new env vars.
- `server/app/models/db.py` (modify) — `FeedbackItem.embedding` column; new `EmbeddingJob` model.
- `server/app/models/schemas.py` (modify) — `EmbeddingJobState`, `EmbeddingJobStatus`.
- `server/app/embeddings/client.py` (create) — `EmbeddingClient` protocol, sentence-transformers
  implementation, truncation helper, `get_embedding_client()`.
- `server/app/embeddings/service.py` (create) — `start_or_resume_job`, `run_job`,
  `DatasetNotFoundError`, `JobAlreadyRunningError`.
- `server/app/embeddings/index.py` (create) — HNSW index singleton, `build_index()`, `search()`.
- `server/app/embeddings/__init__.py` (modify) — rewrite docstring: local sentence-transformers, no
  Voyage AI reference.
- `server/app/api/ingestion.py` (modify) — add the two `.../embed` routes; stays thin.
- `server/app/main.py` (modify) — startup hook calling `build_index()`.
- `server/alembic/versions/xxxx_add_embeddings.py` (create, via autogenerate).
- `server/pyproject.toml` (modify) — add `sentence-transformers`, `hnswlib`.
- `server/tests/test_embeddings.py` (create) — unit tests using a stub `EmbeddingClient` (no network
  calls): batching at the count limit, truncation determinism, idempotent re-run, resume-after-batch-
  failure, HNSW build/search ordering.
- `server/tests/test_api_embeddings.py` (create) — integration tests via `TestClient`, overriding
  `get_embedding_client` with a stub: full ingest (reusing IM-1 fixtures) → embed → status
  round-trip; 404 on unknown dataset; 409 on double-POST while running.
- `client/src/api/**` (regenerate, commit the diff) — via `pnpm --filter client generate:api`.

## Test Plan

- **Unit** (`server/tests/test_embeddings.py`), all against a stub `EmbeddingClient` — no real model
  load, no network:
  - Batching splits exactly at `EMBEDDING_BATCH_SIZE`, including a final partial batch.
  - Truncation: a text exceeding `max_seq_length` is truncated deterministically (same input → same
    truncated output) and logged; a text under the limit is untouched.
  - `embed_documents` and `embed_query` route through the same underlying model call.
  - `build_index()` + `search()`: seed known vectors, assert neighbor order is ascending cosine
    distance.
- **Integration** (`server/tests/test_api_embeddings.py`) via `httpx` + FastAPI `TestClient`,
  `get_embedding_client` dependency-overridden with a stub:
  - Ingest a fixture CSV (IM-1) → `POST .../embed` → `GET .../embed` shows `state="completed"`,
    `items_embedded == items_total`, every row's `embedding` non-`NULL` with the configured
    dimension.
  - Re-`POST` on the same dataset: `items_total: 0`, `items_embedded: 0`, stub records zero calls.
  - `POST` on an unknown UUID → 404. `GET` before any `POST` → 404.
- **Failure injection**: stub `EmbeddingClient` raises on a specific batch index; assert earlier
  batches' rows are embedded and committed, `state="failed"`, `items_failed` equals that batch's
  size, and a subsequent `POST` + `GET` shows the remaining rows completing.
- **Migration**: `uv run alembic upgrade head` → `downgrade -1` → `upgrade head` again, against a
  scratch database pre-populated via the IM-1 ingestion path.
- **Manual**: run against the real `sentence-transformers` model (no stub) with a ~500-row CSV on a
  typical dev laptop; record wall time in the PR description per the Definition of Done below.

## Definition of Done

As IM-1, plus:

- `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` / `EMBEDDING_BATCH_SIZE` documented in
  `server/.env.example`; `VOYAGE_API_KEY` removed.
- Dependencies added: `sentence-transformers`, `hnswlib` (via `uv add`).
- PR description includes measured wall time for a 500-row embed run on a typical dev machine.
- `ruff`, `mypy --strict`, `pytest` all green; `pnpm --filter client generate:api` run and its diff
  committed; `pnpm --filter client build` green; PR opened with `/git-pr` and squash-merged.
