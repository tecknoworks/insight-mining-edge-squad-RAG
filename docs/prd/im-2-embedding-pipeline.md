# IM-2 — Embedding pipeline

**Type:** Story **Epic:** Embeddings **Priority:** P0
**Estimate:** 8 points **Depends on:** IM-1
**Branch:** `feat/server/embedding-pipeline`

## Context

Semantic clustering and chat-with-data both read vectors, not text. This ticket turns every
`feedback_items` row into a stored embedding. It is the single most cost-sensitive stage in the
pipeline — a re-run that re-embeds already-embedded rows burns real money, so idempotency is a
hard requirement, not a nicety.

## Goal

Given a dataset ID, generate an embedding for every feedback item that does not already have one,
store it in a pgvector column, and expose enough progress state that a caller can tell whether the
job is running, finished, or partially failed.

## Scope

**In scope**

- A provider-agnostic embedding client wrapping **Voyage AI** in `app/embeddings/`.
- `embedding` column + vector index migration.
- Trigger endpoint + status endpoint.
- Batching, retry with backoff, rate-limit handling, and idempotent re-runs.

**Out of scope**

- Clustering (IM-3) and retrieval (IM-6) — this ticket only produces and stores vectors.
- Swapping providers at runtime. The provider is chosen by configuration, like the Claude models.
- A background worker/queue system. Use FastAPI `BackgroundTasks` for now; note the ceiling in the
  spec's Constraints section.

## Technical approach

- **Provider.** Voyage AI, per `README.md` and the existing `VOYAGE_API_KEY` slot in
  `server/.env.example`. **Before writing the client, consult the `claude-api` skill and the
  current Voyage documentation to confirm the model ID and its embedding dimension** — the model
  catalogue moves and this PRD does not pin it. Whatever you confirm becomes the default of the new
  `VOYAGE_EMBEDDING_MODEL` env var, and its dimension becomes `EMBEDDING_DIMENSION`.
- **Model choice is system configuration, not application logic** — same rule the Claude models
  follow. Read it from settings; never hardcode it in a call site.
- **Input type matters.** Voyage distinguishes document embeddings from query embeddings. Feedback
  items are embedded as **documents**; IM-6 will embed the user's question as a **query** using the
  same model. Expose both paths from the client module so IM-6 cannot get it wrong.
- **Interface.** Define a narrow protocol (`embed_documents(texts) -> list[list[float]]`,
  `embed_query(text) -> list[float]`) with a Voyage implementation behind it, so a future provider
  swap is a config + one-class change. Do not build a plugin registry.
- **Storage.** Add `feedback_items.embedding` as `pgvector.sqlalchemy.Vector(EMBEDDING_DIMENSION)`,
  nullable. Add an HNSW index with `vector_cosine_ops`. **Cosine is the distance metric for the
  whole project** — clustering (IM-3) and retrieval (IM-6) must use the same one.
- **Batching & resilience.** Batch by both item count and total token/character budget (Voyage
  rejects oversized batches). Retry `429` and `5xx` with exponential backoff + jitter; do not retry
  `4xx` validation errors. A failed batch must not roll back successfully embedded batches —
  commit per batch.
- **Truncation.** Feedback text longer than the model's context limit must be truncated
  deterministically before the call, and the truncation logged. Do not let the provider reject the
  batch.
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
  "model": "<configured voyage model id>",
  "dimension": 1024,
  "error": null,
  "started_at": "...",
  "finished_at": "...",
}
```

Persist job state on the `datasets` row (or a small `embedding_jobs` table) — it must survive a
process restart, so it cannot live in memory.

## New configuration

Add to `app/core/config.py` **and** `server/.env.example`:

- `VOYAGE_EMBEDDING_MODEL` — default = the model ID confirmed during `/spec-plan`
- `EMBEDDING_DIMENSION` — must match the model
- `EMBEDDING_BATCH_SIZE` (default `128`)
- `EMBEDDING_MAX_RETRIES` (default `5`)

## Acceptance criteria

1. `POST /ingestion/datasets/{id}/embed` populates `feedback_items.embedding` for every item in the
   dataset that had `NULL`, and leaves already-embedded items untouched.
2. Calling the endpoint a second time on a fully embedded dataset returns success with
   `items_embedded: 0` and makes **zero** provider API calls. (Assert on the mock's call count.)
3. `GET .../embed` reports accurate `items_total` / `items_embedded` / `items_failed` while the job
   runs and after it finishes, and survives a server restart mid-job (state is in the database, not
   in memory).
4. A `429` or `5xx` from the provider is retried with exponential backoff up to
   `EMBEDDING_MAX_RETRIES`; a `400` is not retried.
5. If one batch fails permanently, previously committed batches remain embedded, `state` becomes
   `failed`, `items_failed` is accurate, and `error` carries a useful message. A subsequent call
   resumes from where it stopped.
6. Feedback text exceeding the model's input limit is truncated deterministically rather than
   causing a provider error.
7. The stored vector length equals `EMBEDDING_DIMENSION` for every embedded row.
8. The HNSW `vector_cosine_ops` index exists after migration, and
   `EXPLAIN` on an ORDER BY `<=>` query shows it being considered.
9. Migration up and down run clean against a database already populated by IM-1.
10. **The Voyage model ID appears nowhere in application code** — only as a settings read. Grep for
    the literal to prove it.
11. No embedding logic in `app/api/`; the route only orchestrates `app/embeddings/`.
12. `client/src/api/` regenerated and committed.

## Test plan

- Unit: batching splits correctly at the count and size limits; retry/backoff triggers on 429/5xx
  and not on 400; truncation is deterministic; the document/query input-type paths are distinct.
  Provider is mocked — **no test may make a live Voyage call.**
- Integration: ingest a fixture CSV (IM-1) → run embed → assert every row has a vector of the right
  length → re-run and assert zero provider calls.
- Failure injection: mock a permanent failure on batch 3 of 5; assert batches 1–2 persist, state is
  `failed`, and a re-run completes batches 3–5 only.
- Manual: run against real Voyage with a ~200-row CSV; record wall time and observed cost in the
  PR description so IM-4/IM-6 can budget.

## Definition of done

As IM-1, plus: `VOYAGE_EMBEDDING_MODEL` / `EMBEDDING_DIMENSION` documented in `server/.env.example`
and the AI Model Configuration table in `README.md` updated to mention the embedding model var.
