# IM-4 — Claude-powered cluster summarization

**Type:** Story **Epic:** Insights **Priority:** P0
**Estimate:** 8 points **Depends on:** IM-3
**Branch:** `feat/server/cluster-summarization`

## Context

A cluster is currently an anonymous bag of rows. This ticket makes it legible: Claude reads a
cluster and returns a short human theme label, a plain-language summary of what the theme is and
why it matters, and representative verbatim quotes.

**Cost optimization:** Summaries are generated **on-demand** (when first viewed) and **cached** rather than
pre-computed for every cluster. This dramatically reduces API calls in workflows where many clusters
are created but only a subset are explored by users. Uses **Haiku** exclusively for cost control.

This is the first Claude call in the codebase and it sets the pattern for IM-6. Get the model-config
discipline right here.

## Goal

When a user requests a summary for a cluster (viewing it in the dashboard), generate a `label`,
`summary`, and 3–5 representative quotes and cache them. Subsequent requests for the same cluster
use the cache until it expires (`SUMMARY_CACHE_TTL_HOURS`). Support a `?force=true` parameter to
bypass the cache.

## Scope

**In scope**

- On-demand summarization endpoint: client requests a summary for a single cluster ID.
- Prompt construction, schema-constrained output, and response validation in `app/insights/`.
- `cluster_summaries` table (caching layer) with TTL-aware retrieval.
- `cluster_quotes` table (or a JSONB column in `cluster_summaries` — decide in the spec).
- Sampling strategy for clusters too large to fit in one prompt.

**Out of scope**

- Chat / RAG — IM-6.
- Any UI — IM-5 consumes these fields.
- Batch pre-computation of summaries; on-demand only.
- A model-selection UI or runtime switching. **Explicitly forbidden by `README.md`.**

## Technical approach

- **Model.** **Hardcoded to `claude-haiku-4-5`** via `ANTHROPIC_SUMMARIZATION_MODEL` (no switching).
  This is a cheap, on-demand task. Read the env var once on startup or per request; the literal
  must not appear in `app/insights/` — only in `config.py` as a default and in `.env.example`.
- **On-demand, not batch.** A single endpoint accepts a `cluster_id` and returns its summary
  (or immediately if cached). The server does not queue or batch multiple clusters — each request
  is independent. This matches user workflow (explore one cluster at a time) and simplifies caching.
- **Cache layer.** Add a `cluster_summaries` table with `(cluster_id, label, summary, quotes, created_at)`.
  Check the cache on incoming request; if hit and `created_at > NOW() - SUMMARY_CACHE_TTL_HOURS`,
  return it. Otherwise, call Claude, store the result, and return it. Accept `?force=true` to
  bypass the cache.
- **Structured output, not prose parsing.** Use the Messages API structured-outputs feature
  (`output_config.format` with a `json_schema`) so the response is guaranteed-parseable. Do not
  regex a JSON blob out of free text, and do not use assistant prefill.
- **Prompt input.** Send a sample of the cluster's feedback items with their `source` and `date`
  when present. Sample deterministically (seeded) and cap by token budget, not row count —
  use `client.messages.count_tokens` to size the sample rather than guessing.
- **Quote fidelity is a correctness requirement.** Every returned quote must be an exact substring
  of a feedback item in that cluster. Validate this in code after the response returns; discard
  quotes that fail and, if fewer than 3 survive, retry once with a prompt that restates the
  constraint. A hallucinated customer quote shown to an executive is the worst failure mode this
  product has.
- **Store provenance.** Persist each quote with its `feedback_item_id`, so the UI can link a quote
  back to its row and IM-7 can scope it.
- **Resilience.** Retry `429`/`5xx` with backoff (the SDK retries twice by default). Handle
  `stop_reason == "refusal"` and `stop_reason == "max_tokens"` as distinct, logged outcomes that
  return an error to the client (do not store a partial summary).

## API contract

```
GET  /clusters/{cluster_id}/summary                → 200 ClusterSummary    (cached or generated on-demand)
                                                    → 404 cluster not found
                                                    → 503 summarization failed (Claude API issue)
GET  /clusters/{cluster_id}/summary?force=true     → 200 ClusterSummary    (bypass cache, always call Claude)
```

Response (`ClusterSummary`):

```jsonc
{
  "cluster_id": "uuid",
  "label": "string, 2-5 words, title case",
  "summary": "string, 2-4 sentences",
  "quotes": ["verbatim string", "..."], // 3-5 items
  "cached_at": "ISO 8601 timestamp", // when this was generated/cached
}
```

Enforced response schema per cluster:

```jsonc
{
  "label": "string, 2-5 words, title case",
  "summary": "string, 2-4 sentences: what the theme is, and why it matters",
  "quotes": ["verbatim string", "..."], // 3-5 items
}
```

## New configuration

- `SUMMARY_CACHE_TTL_HOURS` (default `24`) — how long cached summaries are valid before re-generating
- `SUMMARIZATION_MAX_SAMPLE_TOKENS` (default `8000`) — token budget for the cluster sample sent to Claude
- `SUMMARIZATION_MAX_TOKENS` (default `1024`) — max completion tokens for the response

## Acceptance criteria

1. `GET /clusters/{cluster_id}/summary` calls Claude once, generates a `label`, `summary`, and
   3–5 `quotes`, and persists them in `cluster_summaries` with a `created_at` timestamp.
2. **Every persisted quote is an exact substring of a feedback item belonging to that cluster**,
   and each quote stores the `feedback_item_id` it came from. A test asserts this for every quote.
3. A response containing a quote that is not present in the cluster's items is rejected and retried
   once; if the retry also fails, the endpoint returns **503** and does not store a partial summary.
4. `label` is 2–5 words; `summary` is 2–4 sentences. Enforced by the JSON schema and re-checked in
   code.
5. Repeated calls to the same `cluster_id` within `SUMMARY_CACHE_TTL_HOURS` return the cached
   summary **without calling Claude** (verify via a mock's call count).
6. `GET .../summary?force=true` bypasses the cache, calls Claude, and stores the new result.
7. After `SUMMARY_CACHE_TTL_HOURS`, the next request re-generates and updates the cache.
8. The model ID is read from `settings.anthropic_summarization_model` — hardcoded to `claude-haiku-4-5`.
   **Grep proves no other Claude model literal exists under `app/insights/` or `app/api/`.**
9. Clusters larger than the token budget are sampled deterministically; two runs at the same seed
   send the same sample.
10. A `429` is retried with backoff; a refusal (`stop_reason == "refusal"`) returns **503** without
    storing a partial summary.
11. Token usage per call is logged at INFO.
12. **All prompt text lives in `app/insights/`.** No prompt strings in `app/api/`, `app/clustering/`,
    or `app/models/`.
13. `client/src/api/` regenerated and committed.

## Test plan

- Unit, with the Anthropic client mocked (no live calls in CI): prompt assembly; schema validation;
  the quote-fidelity checker accepts exact substrings and rejects near-misses, paraphrases, and
  quotes belonging to a _different_ cluster; sampling determinism; retry-once-then-fail on repeated
  bad quotes.
- Cache behavior: first call → Claude is called → result cached. Second call within TTL → cache hit,
  Claude not called. Call with `?force=true` → cache bypassed, Claude called. After TTL expiry →
  cache miss, Claude called.
- Error paths: mocked `429` → retried once, then returns **503** if still failing; mocked refusal →
  returns **503**, no partial cache entry.
- Integration: ingest → embed (mocked) → cluster → `GET /clusters/{id}/summary` (mocked) →
  response contains label, summary, and quotes.
- Manual: one real run against a ~500-row CSV. Paste two generated labels + summaries into the PR
  description for a human quality read, and record token cost per summary.

## Definition of done

As IM-1, plus real-run sample output and measured token cost in the PR description.
