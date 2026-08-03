# IM-4 — Claude-powered cluster summarization

**Type:** Story **Epic:** Insights **Priority:** P0
**Estimate:** 8 points **Depends on:** IM-3
**Branch:** `feat/server/cluster-summarization`

## Context

A cluster is currently an anonymous bag of rows. This ticket makes it legible: Claude reads a
cluster and returns a short human theme label, a plain-language summary of what the theme is and
why it matters, and representative verbatim quotes.

This is the first Claude call in the codebase and it sets the pattern for IM-6. Get the model-config
discipline right here.

## Goal

For every cluster in a clustering run, produce and persist a `label`, a `summary`, and 3–5
representative quotes drawn verbatim from that cluster's feedback items.

## Scope

**In scope**

- Prompt construction, schema-constrained output, and response validation in `app/insights/`.
- `cluster_quotes` table (or a JSONB column — decide in the spec) and migration.
- Trigger + status endpoints; `label`/`summary` surfaced on the existing cluster read endpoints.
- Sampling strategy for clusters too large to fit in one prompt.

**Out of scope**

- Chat / RAG — IM-6.
- Any UI — IM-5 consumes these fields.
- Streaming. Summarisation is a batch job; the client polls.
- A model-selection UI or runtime switching. **Explicitly forbidden by `README.md`.**

## Technical approach

- **Model.** Read `settings.anthropic_summarization_model` (default `claude-haiku-4-5`). It is a
  cheap, high-volume batch task and the cheapest tier is sufficient. **Read the `claude-api` skill
  before writing the call.** The literal `claude-haiku-4-5` must not appear in `app/insights/` —
  only in `config.py` as a default and in `.env.example`.
- **Structured output, not prose parsing.** Use the Messages API structured-outputs feature
  (`output_config.format` with a `json_schema`) so the response is guaranteed-parseable. Do not
  regex a JSON blob out of free text, and do not use assistant prefill — prefill returns 400 on
  current models.
- **Prompt input.** For each cluster, send a sample of its feedback items with their `source` and
  `date` when present. Sample deterministically (seeded) and cap by token budget, not row count —
  use `client.messages.count_tokens` to size the sample rather than guessing. Record the sample
  size used on the cluster row.
- **Quote fidelity is a correctness requirement.** Every returned quote must be an exact substring
  of a feedback item in that cluster. Validate this in code after the response returns; discard
  quotes that fail and, if fewer than 3 survive, retry once with a prompt that restates the
  constraint. A hallucinated customer quote shown to an executive is the worst failure mode this
  product has.
- **Store provenance.** Persist each quote with its `feedback_item_id`, so the UI can link a quote
  back to its row and IM-7 can scope it.
- **Cost and concurrency.** Summarise clusters concurrently with a bounded semaphore
  (`SUMMARIZATION_CONCURRENCY`, default 4). Persist per-cluster on success so a mid-run failure does
  not discard completed work. Log `usage.input_tokens` / `usage.output_tokens` per call.
- **Resilience.** Retry `429`/`5xx` with backoff (the SDK retries twice by default — configure
  explicitly). Handle `stop_reason == "refusal"` and `stop_reason == "max_tokens"` as distinct,
  logged, non-crashing outcomes that mark that one cluster failed.
- **Idempotency.** Only summarise clusters where `label IS NULL`, unless `?force=true`.

## API contract

```
POST /clusters/runs/{run_id}/summarize          → 202 SummarizationJobStatus
POST /clusters/runs/{run_id}/summarize?force=true
GET  /clusters/runs/{run_id}/summarize          → 200 SummarizationJobStatus
```

`GET /clusters?dataset_id=` (IM-3) gains `label`, `summary`, and `quotes[]` on each cluster.

Enforced response schema per cluster:

```jsonc
{
  "label": "string, 2-5 words, title case",
  "summary": "string, 2-4 sentences: what the theme is, and why it matters",
  "quotes": ["verbatim string", "..."], // 3-5 items
}
```

## New configuration

`SUMMARIZATION_CONCURRENCY` (default `4`), `SUMMARIZATION_MAX_SAMPLE_TOKENS` (default `8000`),
`SUMMARIZATION_MAX_TOKENS` (default `1024`).

## Acceptance criteria

1. `POST /clusters/runs/{id}/summarize` populates `label` and `summary` on every cluster in the run
   and persists 3–5 quotes per cluster.
2. **Every persisted quote is an exact substring of a feedback item belonging to that cluster**, and
   each quote stores the `feedback_item_id` it came from. A test asserts this for every quote.
3. A response containing a quote that is not present in the cluster's items is rejected and retried
   once; if the retry also fails, that cluster is marked failed rather than persisting a fabricated
   quote.
4. `label` is 2–5 words; `summary` is 2–4 sentences. Enforced by the JSON schema and re-checked in
   code.
5. The model ID is read from `settings.anthropic_summarization_model`. **Grep proves no Claude model
   literal exists anywhere under `app/insights/` or `app/api/`.**
6. Changing `ANTHROPIC_SUMMARIZATION_MODEL` in `.env` and restarting changes the model used, with no
   code change and no API parameter.
7. Clusters larger than the token budget are sampled deterministically; two runs at the same seed
   send the same sample.
8. A `429` is retried with backoff; a refusal (`stop_reason == "refusal"`) marks one cluster failed
   with a clear message and does not abort the run.
9. Re-running without `force=true` skips clusters that already have a `label` and makes zero API
   calls for them.
10. `GET /clusters/runs/{id}/summarize` reports `clusters_total` / `clusters_summarized` /
    `clusters_failed` and survives a restart.
11. Token usage per call is logged at INFO.
12. **All prompt text lives in `app/insights/`.** No prompt strings in `app/api/`, `app/clustering/`,
    or `app/models/`.
13. `client/src/api/` regenerated and committed.

## Test plan

- Unit, with the Anthropic client mocked (no live calls in CI): prompt assembly; schema validation;
  the quote-fidelity checker accepts exact substrings and rejects near-misses, paraphrases, and
  quotes belonging to a _different_ cluster; sampling determinism; retry-once-then-fail on repeated
  bad quotes.
- Error paths: mocked `429` → retried; mocked refusal → single cluster marked failed, run continues.
- Integration: ingest → embed (mocked) → cluster → summarize (mocked) → `GET /clusters` returns
  populated labels, summaries, and quotes.
- Config: monkeypatch `ANTHROPIC_SUMMARIZATION_MODEL`; assert the mocked client received that exact
  string.
- Manual: one real run against a ~500-row CSV. Paste two generated labels + summaries into the PR
  description for a human quality read, and record total token cost.

## Definition of done

As IM-1, plus real-run sample output and measured token cost in the PR description.
