# Feature: Claude-powered cluster summarization

## Goal

Enable users to understand cluster themes at a glance by generating concise human-readable labels, summaries, and representative quotes for each semantic cluster on-demand. Summaries are cached to minimize API costs while supporting forced refresh via `?force=true`. This is the first Claude integration in the codebase and establishes the pattern for cost-optimized, model-agnostic Claude usage.

## Acceptance Criteria

- **API endpoint** `GET /clusters/{cluster_id}/summary` returns a cached or freshly-generated summary without calling Claude twice within `SUMMARY_CACHE_TTL_HOURS`
- **Quote fidelity:** Every returned quote is an exact substring (truncated to ≤500 chars) of a feedback item belonging to that cluster; quotes longer than 500 chars are truncated with `…` appended; if any quote fails the fidelity check, the response is rejected and retried once; if retry fails, return 503 without caching a partial result
- **Response schema** includes `label` (2–5 words, title case), `summary` (2–4 sentences), `quotes` (3–5 items, each ≤500 chars), and `cached_at` (ISO 8601 timestamp)
- **Quote provenance** each quote stores the `feedback_item_id` it came from for UI linking and scoping (IM-7)
- **Deterministic sampling** clusters larger than the token budget are sampled via a seeded random strategy; two runs at the same seed produce identical samples
- **Model hardcoding:** Model ID is read from `settings.anthropic_summarization_model` (env var `ANTHROPIC_SUMMARIZATION_MODEL`, default `claude-haiku-4-5`); grep confirms no other Claude model literal exists under `app/insights/` or `app/api/`
- **Structured output** uses Messages API `output_config.format` with `json_schema` for guaranteed-parseable responses; no regex parsing of prose
- **Error resilience** `429` / `5xx` retried with backoff; `stop_reason == "refusal"` returns 503 without caching; `stop_reason == "max_tokens"` logged and returned as error
- **`?force=true` parameter** bypasses the cache and calls Claude, storing the new result
- **Cache expiry** after `SUMMARY_CACHE_TTL_HOURS`, the next request re-generates and updates the cache
- **Token usage** logged at INFO level per call

## Technical Approach

**Database layer:**

- New `cluster_summaries` table with columns: `cluster_id` (UUID, PK), `label` (str), `summary` (str), `quotes` (JSONB array of `{text, feedback_item_id}`), `created_at` (timestamp)
- On request, check cache; if hit and `created_at > NOW() - SUMMARY_CACHE_TTL_HOURS`, return it; else generate and store

**Prompt & sampling:**

- Sample feedback items from the cluster deterministically (seeded by `cluster_id` hash)
- Cap sample by token budget (`SUMMARIZATION_MAX_SAMPLE_TOKENS`), not row count; use `client.messages.count_tokens` to size
- Send sample with `source` and `date` fields (when present) in the prompt input

**Claude integration (`app/insights/summarizer.py`):**

- Construct prompt requesting `label`, `summary`, and `3–5` quotes
- Use structured output with a JSON schema enforcing the response shape
- Call `client.messages.create()` with `SUMMARIZATION_MAX_TOKENS` (default 1024) as max_tokens
- Post-process: validate every quote as exact substring; discard non-matching; if <3 survive, retry once
- Log token usage; handle refusal and max_tokens as errors (return 503, don't cache)

**API route (`app/api/clusters/{cluster_id}/summary.py`):**

- Parse `cluster_id` (UUID) and optional `force` query param
- Call the summarizer; if cache hit and not forced, return cached result immediately
- If generation needed, call the summarizer; handle Claude errors gracefully

**Configuration:**

- `SUMMARY_CACHE_TTL_HOURS` (default 24)
- `SUMMARIZATION_MAX_SAMPLE_TOKENS` (default 8000)
- `SUMMARIZATION_MAX_TOKENS` (default 1024)
- `ANTHROPIC_SUMMARIZATION_MODEL` (default `claude-haiku-4-5`)

## Edge Cases / Constraints

- **Empty cluster:** Return an error (cluster must have at least 1 item to summarize)
- **Very large cluster:** Sample is deterministically selected; response stays under token limit
- **Long feedback items:** Quotes are truncated to 500 chars; `…` indicates truncation
- **Quote hallucination:** Most critical failure mode; every quote is validated as a substring before persisting
- **Model switching:** Hardcoded to Haiku; changing requires env var re-deploy (no runtime switching)
- **Refusal handling:** If Claude refuses (e.g., on harmful content), return 503 and log; do not cache a refusal
- **429 rate limits:** SDK retries twice by default; additional retries with backoff in the summarizer

## Files to Modify

**Backend:**

- `server/app/models/cluster.py` — add `ClusterSummary` Pydantic schema (response DTO)
- `server/app/models/database.py` — add `ClusterSummary` SQLAlchemy ORM model
- `server/alembic/versions/` — new migration creating `cluster_summaries` table
- `server/app/insights/summarizer.py` — create; core summarization logic (prompt, Claude call, quote validation)
- `server/app/api/clusters.py` — add `GET /clusters/{cluster_id}/summary` route
- `server/app/core/config.py` — add config vars: `SUMMARY_CACHE_TTL_HOURS`, `SUMMARIZATION_MAX_SAMPLE_TOKENS`, `SUMMARIZATION_MAX_TOKENS`, `ANTHROPIC_SUMMARIZATION_MODEL`
- `server/.env.example` — add new env vars

**Client:**

- `client/src/api/` — regenerate from backend OpenAPI schema (via `pnpm generate:api`)

## Test Plan

**Unit tests (`tests/app/insights/test_summarizer.py`):**

- Prompt assembly with various cluster sizes and optional fields
- Structured output schema validation
- Quote-fidelity checker: accepts exact substrings, rejects near-misses / paraphrases / quotes from other clusters
- Sampling determinism: same seed → same sample
- Retry logic: bad quotes → retry once → fail on second bad response

**Integration tests (`tests/app/api/test_clusters_summary.py`):**

- First call to cluster → Claude called → result cached with `created_at`
- Second call within TTL → cache hit, Claude not called (mock verify call count)
- Call with `?force=true` → cache bypassed, Claude called, new result stored
- After TTL expiry → cache miss, Claude called, cache updated
- Error paths: mocked 429 → retried, returns 503 if still failing; mocked refusal → 503, no cache entry

**End-to-end (manual):**

- Run against ~500-row CSV ingest → cluster → summarize
- Capture 2 real label+summary pairs for PR description (human quality read)
- Record token cost per summary

## Definition of Done

- All acceptance criteria met
- All tests pass (unit + integration)
- Model ID hardcoded via env var, verified with grep
- Real-run sample output and measured token cost in PR description
- `client/src/api/` regenerated and committed
