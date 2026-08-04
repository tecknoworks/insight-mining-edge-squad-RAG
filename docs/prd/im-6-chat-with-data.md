# IM-6 — Chat-with-data endpoint + UI

**Type:** Story **Epic:** Insights **Priority:** P1
**Estimate:** 13 points **Depends on:** IM-2 (works better after IM-4)
**Branch:** `feat/server/chat-with-data` then `feat/client/chat-panel`

## Context

The last pipeline stage: let a user ask "what are people saying about checkout this month?" and get
an answer grounded in the actual feedback corpus, not the model's priors. This is RAG over the same
pgvector embeddings IM-2 produced.

**This ticket is large enough to split into two PRs** (backend, then frontend) under one Jira
ticket. The backend PR must merge first.

## Goal

A streaming chat endpoint that retrieves the most semantically relevant feedback for a question,
answers using only that retrieved context, cites the feedback items it used, and refuses to answer
when retrieval returns nothing relevant. Plus a chat panel in the dashboard that consumes it.

## Scope

**In scope**

- Retrieval (`app/embeddings/` for the query vector, `app/insights/` for the RAG orchestration and
  prompt).
- `POST /chat/messages` with SSE streaming, plus conversation persistence.
- Filter support (dataset, source, date range) applied as SQL predicates before vector search.
- Citations mapping answer → feedback item IDs.
- A chat panel in the dashboard.

**Out of scope**

- Multi-user conversation history and sharing (arrives with IM-7).
- Agentic tool use. This is single-turn retrieval + generation with conversation history, not an
  agent loop.
- Re-ranking models. Note it as a future optimisation if precision is poor.

## Technical approach — backend

- **Model.** `settings.anthropic_chat_model` (default **`claude-haiku-4-5`**) — cost-optimized for
  retrieval-grounded Q&A. **Read the `claude-api` skill before writing the call.** Specifically:
  - **Do not pass `temperature`, `top_p`, or `top_k`** — these return **400** on newer Claude models
    when not supported.
  - Use default sampling (no parameter overrides).
  - **Stream.** Use `client.messages.stream(...)`, not a blocking create.
  - If future testing shows Haiku's reasoning is insufficient for complex analysis questions, upgrade
    to Sonnet 5 and document the tradeoff in a follow-up ticket.
- **Query embedding.** Embed the user's question with the **same** sentence-transformers model as
  the documents (from IM-2), using the **query** input type via `embed_query()`. A mismatched model
  or input type silently degrades retrieval quality with no error — assert on it in a test.
- **Retrieval.** Query the in-memory HNSW index (built in IM-2) with the question embedding,
  retrieve the top `CHAT_TOP_K` items by cosine distance, then **apply `dataset_id`, `source`, and
  date filters as SQL WHERE predicates on the result set**. This ensures no data leaks across orgs
  or outside the requested scope. Do not post-filter without the SQL layer — you must respect
  authorization boundaries.
- **Relevance floor.** Discard retrieved items whose cosine distance exceeds
  `CHAT_MAX_DISTANCE`. If nothing survives, return a grounded "I don't have feedback about that"
  answer **without calling Claude**. This is the anti-hallucination guardrail.
- **Prompt.** System prompt in `app/insights/` instructing the model to answer _only_ from the
  supplied feedback, to say so when the feedback does not cover the question, and to reference items
  by the numeric index it is given. Include each item's `source` and `date` so temporal and
  channel questions work. **All prompt text lives in `app/insights/`, never in `app/api/`.**
- **Citations.** Map the indices the model references back to `feedback_item_id`s and emit them as a
  terminal SSE event, so the UI can render clickable sources. Each citation must include the
  `feedback_item_id`, truncated `excerpt` (max 200 chars), `source`, and `date` if present.
- **Conversation history.** Persist `conversations` and `chat_messages` tables. Send prior turns with
  each request (the API is stateless). Cap history by token budget using
  `client.messages.count_tokens`; drop oldest turns first. Never send more than
  `CHAT_MAX_HISTORY_TOKENS` tokens of prior context.
- **Transport.** `StreamingResponse` with `text/event-stream` and `Transfer-Encoding: chunked`.
  **Event order (strictly):** `token*` (zero or more), then `citations` (once), then `done` (once).
  If an error occurs, emit `error` and close the stream immediately (do not send `done`).

## Technical approach — frontend

- **The generated client cannot consume SSE.** `openapi-ts` will emit a function for the endpoint
  whose response type is unusable for streaming. Write a small hand-rolled `fetch` +
  `ReadableStream` reader in **`client/src/lib/chatStream.ts`** — **not** in `client/src/api/`,
  which stays generated-only. Use the generated types for the request/response _shapes_.
- Chat panel renders streaming tokens as they arrive, shows citations as chips under each answer,
  and clicking a citation opens the corresponding feedback item.
- Conversation state lives in `client/src/store/`, scoped to the selected dataset.

## API contract

```
POST /chat/messages     (SSE)
  { "conversation_id": "uuid | null", "dataset_id": "uuid",
    "message": "What are people saying about checkout this month?",
    "filters": { "source": ["support ticket"], "date_from": "2026-01-01", "date_to": "2026-08-03" } }

  Response stream (in order):
  event: token      data: {"text": "People are saying..."}
  event: token      data: {"text": " checkout is..."}
  ... (more tokens)
  event: citations  data: {"items": [
    {"feedback_item_id": "...", "excerpt": "checkout failed with error", "source": "support ticket", "date": "2026-08-01"},
    ...
  ]}
  event: done       data: {"conversation_id": "uuid", "message_id": "uuid"}

GET /chat/conversations/{id}   → 200 { id, created_at, messages: [...] }
```

Error example (stream ends early):

```
  event: token      data: {"text": "..."}
  event: error      data: {"message": "API rate limit exceeded"}
  [stream closes without done or citations]
```

## New configuration

`CHAT_TOP_K` (default `20`), `CHAT_MAX_DISTANCE` (default `0.6` — tune empirically and record the
basis in the PR), `CHAT_MAX_HISTORY_TOKENS` (default `20000`), `CHAT_MAX_TOKENS` (default `8000`).

## Acceptance criteria

1. `POST /chat/messages` streams tokens over SSE and terminates with a `done` event carrying the
   conversation and message IDs.
2. The query is embedded with the same model as the documents and with the **query** input type. A
   test asserts the embedding client was called with the query path, not the document path.
3. Retrieval returns the top `CHAT_TOP_K` items by cosine distance, restricted to the requested
   dataset.
4. `source` and date filters are applied **as SQL predicates before** the top-k limit. A test proves
   that filtering to a source with few matches still returns those matches (not zero).
5. When no retrieved item is within `CHAT_MAX_DISTANCE`, the endpoint returns a grounded
   "no relevant feedback" answer and **makes zero Claude API calls**. Asserted on the mock.
6. The `citations` event lists the feedback items actually used, and every cited ID exists in the
   requested dataset.
7. A question whose answer is not present in the corpus produces an explicit "the feedback doesn't
   cover this" style answer rather than an invented one. Tested with a fixture corpus about
   shipping and a question about pricing.
8. The model ID comes from `settings.anthropic_chat_model`, defaulting to `claude-haiku-4-5`.
   **No Claude model literal exists in application code** (grep-proven). Changing the env var
   changes the model with no code change.
9. **No `temperature`, `top_p`, or `top_k` is sent** on any Claude request (grep-proven — these
   parameters either cause errors or are unsupported on newer models).
10. Conversation history is persisted and replayed on subsequent turns; history is truncated by
    token budget, oldest-first, without breaking the turn structure.
11. A provider error mid-stream emits an `error` event and closes the stream cleanly — the client
    never hangs.
12. The chat panel renders tokens incrementally (visible streaming, not a single flush at the end),
    shows citation chips, and clicking a chip reveals the source feedback item.
13. **`client/src/api/` contains no hand-written streaming code.** The SSE reader lives in
    `client/src/lib/`.
14. All prompt text lives in `app/insights/`; retrieval SQL lives in the backend module layer, not
    in `app/api/chat.py`.
15. `pnpm --filter client build` passes.

## Test plan

- Unit (Claude + sentence-transformers mocked): query-embedding input type; filters applied as SQL
  predicates (not post-filtering); relevance-floor short-circuit makes zero Claude calls; history
  truncation; citation index → item ID mapping; SSE event ordering strict (`token* → citations → done`).
- Integration: ingest a two-topic fixture corpus → embed (stubbed deterministic embedder) → ask an
  in-corpus question (answer cites the right topic's items) and an out-of-corpus question (answer
  declines with no Claude call). Assert HNSW index is queried, not raw embeddings.
- Streaming: assert event ordering strict, that a mocked mid-stream failure emits `error` without
  `done`, and stream closes cleanly.
- Frontend: streaming render test; citation click-through; error-state render; verify citations are
  tied to feedback items and don't leak across orgs.
- Manual: real run against a ~1000-row dataset; paste one good and one deliberately out-of-scope
  Q&A into the PR description. Record token usage and latency for the good Q&A.

## Definition of done

Two PRs (backend, then frontend), each squash-merged. `client/src/api/` regenerated after the
backend PR. Sample Q&A transcripts in the PR description.
