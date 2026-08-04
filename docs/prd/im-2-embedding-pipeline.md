# IM-2 — Embedding pipeline

**Type:** Story **Epic:** Embeddings **Priority:** P0
**Estimate:** 8 points **Depends on:** IM-1
**Branch:** `feat/server/embedding-pipeline`

## Context

Semantic clustering and chat-with-data both read vectors, not text. This ticket turns every
`feedback_items` row into an embedding using **open-source models** (sentence-transformers) that run locally.
The cost strategy trades API calls for modest computation — zero per-embedding fees, but models run on
developer/server hardware. Idempotency is still critical: a re-run that re-embeds already-embedded rows
wastes CPU and time.

## Goal

Given a dataset ID, generate an embedding for every feedback item that does not already have one,
store it in SQLite, and expose enough progress state that a caller can tell whether the
job is running, finished, or partially failed. Embeddings are indexed in an in-memory HNSW index
(`hnswlib`) for fast similarity search.

## Scope

**In scope**

- A provider-agnostic embedding client wrapping open-source **sentence-transformers** in `app/embeddings/`.
- `embedding` column (BLOB, binary vector) + in-memory HNSW index.
- Trigger endpoint + status endpoint.
- Batching and idempotent re-runs (no external rate limits to manage).

**Out of scope**

- Clustering (IM-3) and retrieval (IM-6) — this ticket only produces and stores vectors.
- Swapping providers at runtime. The model is chosen by configuration via `EMBEDDING_MODEL`.
- A background worker/queue system. Use FastAPI `BackgroundTasks` for now; note the ceiling in the
  spec's Constraints section.

## Technical approach

- **Provider.** Open-source embeddings via `sentence-transformers` library. **Default model:
  `all-MiniLM-L6-v2`** (384 dimensions, ~33M params, runs on CPU in <1ms/item on modern hardware).
  Model is configurable via `EMBEDDING_MODEL` env var for swaps to other sentence-transformers
  models (e.g., `all-mpnet-base-v2` for higher quality, or quantized variants for faster inference).
- **Model choice is system configuration, not application logic**. Read `EMBEDDING_MODEL` and
  `EMBEDDING_DIMENSION` from settings; never hardcode them in a call site. Changing the env var
  and restarting the server changes the model with no code change.
- **Input type matters.** The `sentence-transformers` library supports both document and query
  embeddings via the same underlying model (no separate input type). For consistency with IM-6,
  expose two helper functions: `embed_documents(texts)` for feedback and `embed_query(text)` for
  user questions, even though both use the same model internally.
- **Interface.** Define a narrow protocol (`embed_documents(texts) -> list[list[float]]`,
  `embed_query(text) -> list[float]`) in `app/embeddings/client.py` with a sentence-transformers
  implementation behind it, so a future provider swap is a config + one-class change.
- **Storage.** Add `feedback_items.embedding` as a BLOB column (binary vector) in SQLite. On app
  startup or during `embed` endpoint, load all embeddings into an in-memory `hnswlib.Index`
  (HNSW graph) keyed by `feedback_item_id`. **Cosine is the distance metric for the whole project**
  — clustering (IM-3) and retrieval (IM-6) must use the same one. Rebuild the index on each embedding run.
- **Batching.** Batch embeddings into groups of `EMBEDDING_BATCH_SIZE` (default 32) to balance
  memory and inference speed. Process batches sequentially; no parallelization needed (single model
  is already fast).
- **Truncation.** Feedback text longer than the model's context limit (512 tokens for MiniLM) must
  be truncated deterministically before the call, and the truncation logged.
- **Idempotency.** Only select rows `WHERE embedding IS NULL`. Re-invoking the endpoint on a fully
  embedded dataset is a no-op that returns success with `items_embedded: 0`.

## API contract

```
POST /ingestion/datasets/{id}/embed   → 202 EmbeddingJobStatus   (starts/resumes the job)
                                      → 404 unknown dataset
                                      → 409 a job is already running for this dataset
GET  /ingestion/datasets/{id}/embed   → 200 EmbeddingJobStatus
```

```jsonc
{
  "dataset_id": "uuid",
  "state": "pending | running | completed | failed",
  "items_total": 1487,
  "items_embedded": 1487,
  "items_failed": 0,
  "model": "all-MiniLM-L6-v2",
  "dimension": 384,
  "error": null,
  "started_at": "...",
  "finished_at": "...",
}
```

- `model` is read from `EMBEDDING_MODEL` at runtime and reflects the currently configured model.
- `dimension` must match the model's output dimensionality (384 for MiniLM, 768 for MPNet, etc.).
- Persist job state on the `datasets` row (or a small `embedding_jobs` table) — it must survive a
  process restart, so it cannot live in memory.

## New configuration

Add to `app/core/config.py` **and** `server/.env.example`:

- `EMBEDDING_MODEL` (default `all-MiniLM-L6-v2`) — sentence-transformers model ID
- `EMBEDDING_DIMENSION` (default `384`) — must match the model
- `EMBEDDING_BATCH_SIZE` (default `32`)

## Acceptance criteria

1. `POST /ingestion/datasets/{id}/embed` populates `feedback_items.embedding` for every item in the
   dataset that had `NULL`, and leaves already-embedded items untouched.
2. Calling the endpoint a second time on a fully embedded dataset returns success with
   `items_embedded: 0` and does **zero** model inference calls (skip batches with no unembed rows).
3. `GET .../embed` reports accurate `items_total` / `items_embedded` / `items_failed` while the job
   runs and after it finishes, and survives a server restart mid-job (state is in the database, not
   in memory).
4. If one batch fails (e.g., memory OOM), previously committed batches remain embedded, `state`
   becomes `failed`, `items_failed` is accurate, and `error` carries a useful message. A subsequent
   call resumes from where it stopped.
5. Feedback text exceeding the model's context limit (512 tokens for MiniLM) is truncated
   deterministically rather than causing an inference error; truncation is logged.
6. The stored vector length equals `EMBEDDING_DIMENSION` for every embedded row.
7. The in-memory HNSW index is built on app startup and on every embed completion; index size
   equals the number of embedded rows.
8. A similarity search using the HNSW index returns results ordered by cosine distance (ascending).
9. Migration up and down run clean against a database already populated by IM-1.
10. **The model ID appears nowhere in application code** — only as a settings read (`EMBEDDING_MODEL`).
11. No embedding logic in `app/api/`; the route only orchestrates `app/embeddings/`.
12. `client/src/api/` regenerated and committed.

## Test plan

- Unit: batching splits correctly at the count limit; truncation is deterministic; the
  document/query helper functions both call the same model correctly. No external network calls.
- Integration: ingest a fixture CSV (IM-1) → run embed → assert every row has a vector of the right
  length → HNSW index rebuilds and can retrieve neighbors → re-run and assert zero new embeddings.
- Failure injection: mock a permanent OOM error on batch 3 of 5; assert batches 1–2 persist, state
  is `failed`, and a re-run completes batches 3–5 only.
- Manual: run against real sentence-transformers with a ~500-row CSV on a typical development
  laptop; record wall time in the PR description so IM-4/IM-6 can understand latency.

## Definition of done

As IM-1, plus:

- `EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` / `EMBEDDING_BATCH_SIZE` documented in `server/.env.example`
- Dependencies added: `sentence-transformers`, `hnswlib` (via `uv add`)
- PR description includes measured wall time for a 500-row embed run on a typical dev machine
