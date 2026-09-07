# Feature: Chat-with-data (RAG over the feedback corpus)

## Goal

Let a user ask "what are people saying about checkout this month?" and get an answer grounded in the
actual feedback corpus rather than the model's priors. A streaming endpoint embeds the question with
the same sentence-transformers model that embedded the documents, retrieves the most semantically
relevant feedback within the requested dataset and filters, answers using only that retrieved context,
cites the feedback items it used, and refuses to answer when nothing relevant is retrieved. A chat
panel in the dashboard consumes it. This is the last pipeline stage and the second Claude integration,
following the cost-optimized, model-agnostic pattern IM-4 established.

## Acceptance Criteria

- **Streaming endpoint** `POST /chat/messages` streams tokens over SSE and terminates with a `done`
  event carrying `conversation_id` and `message_id`. Event order is strictly `token*` → `citations` →
  `done`
- **Query embedding** the question is embedded via `EmbeddingClient.embed_query()` — the same model as
  the documents. A test asserts the query path was called, not `embed_documents`
- **Retrieval scope** returns the top `CHAT_TOP_K` items **of the filtered candidate set**, ranked
  exactly by cosine distance, restricted to the requested `dataset_id`
- **Filters precede top-k** `source` and date filters are applied as SQL predicates that build the
  candidate set **before** any ranking or limit. A test proves that filtering to a source with only a
  few matches returns those matches, not zero
- **Relevance floor** when no candidate is within `CHAT_MAX_DISTANCE`, the endpoint returns a grounded
  "no relevant feedback" answer and makes **zero** Claude API calls, asserted on the injected client
- **Citations** the `citations` event lists only the items the answer actually referenced; every cited
  `feedback_item_id` belongs to the requested dataset. Each citation carries `feedback_item_id`,
  `excerpt` (≤200 chars), and `source` / `date` when present
- **Grounded refusal** a question whose answer is absent from the corpus produces an explicit "the
  feedback doesn't cover this" answer rather than an invented one
- **Model configuration** the model ID is read from `settings.anthropic_chat_model`, default
  `claude-haiku-4-5`. No Claude model literal exists under `app/api/`, `app/insights/`,
  `app/clustering/`, or `app/embeddings/` (grep-proven; `app/core/config.py` defaults are
  configuration, not application code)
- **No sampling parameters** the chat request sends no `temperature`, `top_p`, or `top_k`
- **Conversation history** persisted and replayed on later turns; truncated by token budget
  oldest-first without breaking turn structure and never dropping the current user message
- **Mid-stream failure** a provider error emits an `error` event and closes the stream — no `done`, no
  `citations`, and the client never hangs
- **Incremental render** the chat panel renders tokens as they arrive (visible streaming, not one
  flush at the end), shows citation chips, and clicking a chip reveals the source feedback item
- **Generated client stays generated** `client/src/api/` contains no hand-written streaming code; the
  SSE reader lives in `client/src/lib/chatStream.ts`
- **Layer discipline** all prompt text lives in `app/insights/`; all retrieval SQL lives in the module
  layer, not in `app/api/chat.py`
- **Build passes** `pnpm --filter client build` succeeds

## Technical Approach

### Corrections to the PRD this spec supersedes

The PRD (`docs/prd/im-6-chat-with-data.md`) is authoritative on intent but four of its technical
claims are wrong against this codebase and its pinned dependencies. Resolved here so the implementer
does not have to improvise:

1. **Retrieval order.** The PRD says query the HNSW index and _then_ apply filters
   (`docs/PRD-FIXES.md:18` states the order as "HNSW search → SQL fetch with filters"). That is
   post-filtering, and it makes the PRD's own AC 4 unsatisfiable: with 50k items and 20 rows from a
   rare source, the global top-20 contains none of them and the filtered result is empty. **Retract
   that ordering.** Filters build the candidate set first.
2. **`assert HNSW index is queried, not raw embeddings`** (PRD test plan) conflicts with two numbered
   correctness ACs. The ACs win; see "Retrieval" below for the two invariants that replace it.
3. **Chat model default.** AC 8 and `CLAUDE.md` require `claude-haiku-4-5`; `app/core/config.py:43`
   currently says `claude-sonnet-5`. Change the default.
4. **AC 9's rationale.** The PRD says sampling params "return 400 on newer Claude models". They are
   _accepted_ on `claude-haiku-4-5`; they are rejected with 400 on Sonnet 5 and Opus 4.7+. The
   constraint stands, for a better reason: `ANTHROPIC_CHAT_MODEL` is env-configurable, so omitting
   sampling params is forward-compatibility insurance — pointing the env var at Sonnet 5 must not
   require a code change. (`app/insights/summarizer.py:255` sends `temperature=1` with a stale comment
   claiming structured output requires it. Out of scope here; flagged as a follow-up.)

Also drop the PRD's `Transfer-Encoding: chunked` — the ASGI server owns hop-by-hop framing and setting
it by hand risks invalid framing.

### Prerequisite fix

`app/embeddings/client.py:85` calls `self._model.get_embedding_dimension()`. The real
sentence-transformers method is `get_sentence_embedding_dimension()`. Every existing test stubs the
embedding client, so this line has never executed — it raises `AttributeError` on the first real model
load, which is exactly when chat embeds a live question. Fix it and add a test that constructs the real
client, since nothing covers that path today.

### Retrieval (`app/insights/retrieval.py`)

The only retrieval SQL in the codebase. One query carrying every predicate, then exact ranking:

```
select(FeedbackItem.id, FeedbackItem.embedding, FeedbackItem.feedback_text,
       FeedbackItem.source, FeedbackItem.submitted_at)
  .where(FeedbackItem.dataset_id == dataset_id,
         FeedbackItem.embedding.is_not(None),
         # + source.in_(...) when given, + date bounds when given
  )
```

Then decode the candidate vectors with the canonical
`np.frombuffer(blob, dtype=np.float32)` (matching `app/clustering/service.py:93`), compute cosine
distance as `1 - cosine_similarity` — the same metric as `hnswlib(space="cosine")`, so
`CHAT_MAX_DISTANCE` is comparable to IM-3's numbers — take the top `CHAT_TOP_K` via `np.argpartition`
plus a sort of that slice, and drop anything beyond `CHAT_MAX_DISTANCE`.

**Why exact search and not the HNSW index.** hnswlib 0.8.0 does support `knn_query(..., filter=...)`,
but the filter gates result-heap insertion without pruning traversal. On a restrictive filter the
search degenerates into a near-exhaustive graph walk with a GIL-taking Python callback per visited node
— slower than a linear scan in precisely the case AC 4 tests — while on a permissive filter early
termination re-engages and the result is only _approximately_ the top-k of the filtered set, making
AC 3 unfalsifiable. A linear scan over the filtered candidates is exact by construction, costs
single-digit milliseconds at this project's scale, and makes dataset scoping structural rather than
dependent on a filter callback. Note the HNSW index has **zero production callers** today, so this
does not make it dead code — it already is. It remains IM-2's deliverable and the substrate for a
future re-ranking or scale ticket; IM-6 is not that ticket.

Two invariants replace the PRD's "assert HNSW is queried":

- Retrieval never loads an embedding for a row outside the requested dataset and filter set — this is
  the authorization property that matters, and the one a post-filtering design cannot provide
- Ranking is exact: the returned order equals a brute-force cosine ranking over the filtered candidate
  set

### Claude call (`app/insights/chat.py`, `app/insights/prompts.py`)

`client.messages.stream(...)` on the sync client (`anthropic` 0.117.0), with
`model=settings.anthropic_chat_model`, `max_tokens=settings.chat_max_tokens`, a real top-level
`system=` prompt, and nothing else. Specifically **no** `temperature` / `top_p` / `top_k` (AC 9), **no**
`output_config.effort` (errors on Haiku 4.5), and **no** `thinking` (Haiku 4.5 takes the older
`budget_tokens` form, and grounded Q&A does not need it). Call `stream.get_final_message()` inside the
`with` block to log token usage and check `stop_reason`.

The system prompt instructs the model to answer only from the supplied feedback, to say plainly when
the feedback does not cover the question, and to reference items by the numeric index it is given. Each
retrieved item is rendered with its `source` and `date` so temporal and channel questions work, reusing
the `Feedback:/Source:/Date:` block format already established at `summarizer.py:225`.

Error handling uses a most-specific-first chain (`NotFoundError` → `RateLimitError` → `APIStatusError`
→ `APIConnectionError`) rather than IM-4's blanket `except Exception`.

### Transport — SSE

**Verify this first, before writing the handler:**

```bash
cd server && uv run python -c "from fastapi.sse import EventSourceResponse; print('native SSE ok')"
```

FastAPI is pinned at 0.139.2 (Starlette 1.3.1), which reportedly ships native SSE with a first-class
sync-generator code path. This was not verifiable while writing the spec — no venv is installed on the
authoring machine. Both outcomes are supported and produce identical bytes on the wire:

- **Present:** `response_class=EventSourceResponse`, yield `ServerSentEvent(event=..., data=...)`
- **Absent:** `StreamingResponse(gen, media_type="text/event-stream")`, format frames by hand

Either way the handler is a **sync `def` generator**. `async def` is wrong: the body blocks on
`anthropic`'s sync HTTP stream and on SQLAlchemy, which would stall the event loop. Sync generators are
run in a threadpool, match the repo's all-sync handler convention, and need no new dependency — do
**not** add `sse-starlette`. Set `Cache-Control: no-cache` and `X-Accel-Buffering: no` (the usual cause
of "streams locally, flushes all at once behind nginx").

If FastAPI's native SSE producer injects keepalive comments (`: ping`), the client contract must
tolerate them — see Frontend.

### Two structural rules

**All fallible work happens in a dependency, before any byte is sent.** A `resolve_turn` dependency in
`app/api/chat.py` does the dataset/conversation lookups, embeds the query, retrieves, applies the
distance floor, truncates history, and assembles the prompt — returning a `PreparedTurn`. Once the
response has started, headers are gone and `HTTPException` is useless, so every 404/422/503 must be
decided here. This also makes AC 5 structural rather than merely mock-asserted: the relevance-floor
short-circuit is decided before the Anthropic client is ever touched.

**Session lifetime.** Reads and the user-message write happen inside `resolve_turn` under normal
request scope via `Depends(get_db)`. The generator opens its **own** short-lived `SessionLocal()` for
the single final assistant-message commit — the precedent `app/embeddings/service.py:98` already
documents for work that outlives request scope. This avoids depending on whether a `Depends(get_db)`
session survives a streaming body (version-sensitive), and avoids relying on `finally` in a generator
that may be abandoned mid-`yield` on client disconnect and finalized at GC.

**Persist before emitting `citations`,** so a persistence failure can only ever produce `error` before
`citations` — never after, which AC 11 forbids.

### Citations (`app/insights/citations.py`)

Retrieved items are numbered `[1]…[N]` in the prompt. Extraction runs a regex over the **accumulated**
answer, never per chunk — a token boundary will split `[1` / `2]`. Accept comma groups
(`\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]`) and split them. Do not attempt prose forms like "item 3"; the
prompt is what fixes that, and the ambiguity cost exceeds the recall gain.

Validation mirrors `summarizer._validate_quotes` — trust nothing the model says about provenance: drop
out-of-range indices with a logged warning, de-duplicate preserving first appearance, and map to
`feedback_item_id` **from the server-side retrieval list only**. Because that list came from a
dataset-scoped SQL query, AC 6 is then true by construction. If the answer cites nothing, emit
`items: []` — never fall back to "all retrieved items", which would misreport what was used.

Excerpts truncate `feedback_text` to 200 chars at a word boundary with `…`.
`summarizer._truncate_quote` is the same function at a different constant — extract a shared helper
rather than writing a second copy.

### Persistence

Two new tables, one Alembic migration chained onto `f8c2a1b3d4e5`:

- `conversations` — `id` (UUID PK), `dataset_id` (FK CASCADE, indexed), `title` (nullable),
  `created_at`. `dataset_id` also gives IM-7 its hook for `organization_id`
- `chat_messages` — `id` (UUID PK), `conversation_id` (FK CASCADE, indexed), `role`, `content`,
  `citations` (JSON, nullable), `sequence` (int), `created_at`, with
  `UniqueConstraint("conversation_id", "sequence")`

**`sequence` is required, not decorative:** `created_at` alone ties for the two messages of a single
turn, and `GET /chat/conversations/{id}` would replay them in the wrong order. It mirrors
`feedback_items.row_number` and the existing `uq_cluster_assignments_run_item`. Use the established
`Enum(..., native_enum=False)` pattern for `role` and the `_utcnow` default for timestamps (naive UTC —
SQLite has no `timestamptz`).

History truncation drops whole `(user, assistant)` pairs oldest-first, never leaves a leading
`assistant` (the API requires `messages[0].role == "user"`), and never drops the current user message.
Do **not** copy `summarizer._sample_cluster_items`, which makes one `count_tokens` HTTPS round-trip
_per item_ in a loop; estimate locally to select, then verify once with a single `count_tokens` call.

### Testability

Handlers currently call `get_settings()` directly and construct `Anthropic(...)` inline, which is why
`test_api_clusters.py:543`'s `dependency_overrides[get_settings]` is inert — it passes only because CI
has no API key, and it would fail on a developer machine that has one. Minimal change, following the
existing `Depends(get_embedding_client)` precedent:

- New `get_anthropic_client() -> Anthropic | None` provider, `@lru_cache`d, returning `None` when no
  key is configured (preserving the "no key → 503" behaviour without raising at DI time). This also
  fixes a real inefficiency — `clusters.py:195` and `health.py:43` build a fresh client per request
- New chat code takes `settings: Settings = Depends(get_settings)` and
  `Depends(get_anthropic_client)`
- A 2-line fix to `get_cluster_summary` (add the `Depends(get_settings)` parameter, delete the in-body
  call) so the existing inert test becomes real. Do **not** refactor IM-4's module layer — it already
  takes both as parameters; only the handler reads globals

### Configuration

- `CHAT_TOP_K` (default `20`)
- `CHAT_MAX_DISTANCE` (default `0.6` — tune empirically and record the basis in the PR)
- `CHAT_MAX_HISTORY_TOKENS` (default `20000`)
- `CHAT_MAX_TOKENS` (default `8000`)
- `ANTHROPIC_CHAT_MODEL` — change the default from `claude-sonnet-5` to `claude-haiku-4-5`

### Frontend

The generated client cannot consume SSE, so `client/src/lib/chatStream.ts` holds a hand-rolled `fetch`

- `ReadableStream` reader — outside `client/src/api/`, which stays generated-only (AC 13). It uses the
  generated types for request/response _shapes_. Two requirements:

* **Skip lines beginning with `:`** — SSE keepalive comments. A naive parser that splits on `\n\n` and
  expects `event:` breaks the first time the initial token takes longer than the keepalive interval,
  which a cold sentence-transformers load plus retrieval will do
* **Import the base URL from `lib/apiClient.ts`** rather than re-deriving it. `hooks/useLlmHealth.ts`
  already drifted here, reading `VITE_API_BASE_URL` while `apiClient.ts` reads `VITE_API_URL`

`ChatPanel` follows house conventions: named function export with a local props interface, inline
`style={{}}` objects (no CSS modules, no Tailwind — `index.css` is the only stylesheet),
early-return-per-state for loading/error/empty. Citation chips reuse the `blockquote` treatment from
`ClusterDetail.tsx:206`; clicking one reveals the source feedback item. Conversation state lives in
`client/src/store/ChatContext.tsx`, scoped to the selected dataset, following `DatasetContext`'s
`useState` + `useMemo` + throwing-hook shape (providers hold state; fetches live in the component).
Render tokens as plain text — **no markdown dependency** and no `dangerouslySetInnerHTML`.

## Edge Cases / Constraints

- **Inclusive `date_to` off-by-one:** `submitted_at` is a naive datetime and the filter input is a
  date, so `submitted_at <= date_to` silently drops everything submitted later that same day. Use
  `>= date_from` and `< date_to + 1 day`. AC 4's test can pass while the filter is a day wrong — add
  an explicit boundary test
- **Stale-dimension embeddings:** nothing invalidates `feedback_items.embedding` when
  `EMBEDDING_DIMENSION` changes, and `np.frombuffer` happily returns a wrong-length vector. Guard
  `len(blob) == dimension * 4` and skip mismatches with a warning
- **Empty or unembedded dataset:** takes the grounded-refusal path with zero Claude calls, same as the
  relevance floor
- **Client disconnect mid-stream:** the generator is abandoned, so the assistant turn may never be
  persisted. The _user_ message is committed in `resolve_turn`, so it is never lost
- **`stop_reason == "max_tokens"`:** the answer is truncated; log a warning and still emit `citations`
  and `done` — the partial answer is already streamed and cannot be retracted
- **Newlines in tokens:** always JSON-encode the event payload. A literal `\n` interpolated into a
  `data:` line terminates the frame
- **Prompt budget:** the retrieved-context block is not truncatable. If context alone exceeds the
  budget, reduce `CHAT_TOP_K` for that turn and **renumber before prompting** — never after, or indices
  point at items the model never saw
- **`operationId` collisions:** `app/main.py:29` uses the handler function name as the OpenAPI
  `operationId`, and a collision is silent. Name them `post_chat_message` and `get_conversation`
- **HNSW test pollution:** the index globals are never reset between tests —
  `test_embeddings.py:144` leaves a 4-dimensional index in place. Any index-touching test needs an
  explicit reset fixture
- **Out of scope:** multi-user history and sharing (IM-7), agentic tool use, re-ranking models. Note
  re-ranking as a future optimisation if precision proves poor

## Files to Modify

**Backend — create:**

- `server/app/insights/retrieval.py` — the only retrieval SQL; exact cosine ranking + distance floor
- `server/app/insights/prompts.py` — `CHAT_SYSTEM_PROMPT`, `format_context_block`
- `server/app/insights/citations.py` — index parsing, validation, excerpt truncation
- `server/app/insights/chat.py` — `PreparedTurn`, `prepare_turn`, `truncate_history`, `stream_turn`,
  `persist_turn`
- `server/alembic/versions/` — one migration creating `conversations` + `chat_messages`
- `server/tests/test_insights_retrieval.py`, `test_insights_chat.py`, `test_api_chat.py`

**Backend — modify:**

- `server/app/api/chat.py` — stub router → `resolve_turn` dependency + the two handlers
- `server/app/core/config.py` — four `chat_*` settings; `anthropic_chat_model` default →
  `claude-haiku-4-5`
- `server/.env.example` — the same new vars and changed default
- `server/app/models/db.py` — `Conversation`, `ChatMessage` ORM models
- `server/app/models/schemas.py` — request/response DTOs and SSE payload models
- `server/app/embeddings/client.py` — prerequisite `get_sentence_embedding_dimension` fix
- `server/app/api/clusters.py` — 2-line `Depends(get_settings)` fix
- `server/app/insights/summarizer.py` — extract the shared excerpt-truncation helper only

**Client:**

- `client/src/lib/chatStream.ts` (create) — SSE reader
- `client/src/components/ChatPanel.tsx` (create)
- `client/src/store/ChatContext.tsx` (create)
- `client/src/components/__tests__/ChatPanel.test.tsx` (create)
- `client/src/pages/DashboardPage.tsx` — mount the panel in the existing flex row
- `client/src/api/` — regenerate via `pnpm generate:api` after the routes land

## Test Plan

**Unit (Claude and sentence-transformers mocked):**

- Query embedding uses `embed_query`, not `embed_documents`
- Filters are SQL predicates: a rare-source filter returns its few matches, not zero
- Ranking is exact — equals a brute-force cosine ranking over the filtered candidate set
- No embedding is loaded for a row outside the dataset + filter set
- `date_to` boundary: an item submitted late on the `date_to` day is included
- Relevance-floor short-circuit makes zero Claude calls
- History truncation: drops whole pairs oldest-first, never leads with `assistant`, never drops the
  current user message
- Citation mapping: valid indices map correctly; out-of-range indices are dropped; no citations → `[]`
- Excerpt truncation at 200 chars on a word boundary
- Stale-dimension blob is skipped rather than decoded
- The real `SentenceTransformerEmbeddingClient` constructs without raising (covers the prerequisite
  fix — nothing tests this today)

**Integration (`TestClient`, hand-written fake Anthropic client):**

Use a hand-written fake in the existing `StubEmbeddingClient` style, not `MagicMock` — the fake must
act as a context manager exposing `text_stream` and `get_final_message()`, which a `MagicMock` cannot
do cleanly. Inject it via `app.dependency_overrides[get_anthropic_client]`.

- Ingest a two-topic fixture corpus (e.g. shipping and pricing) → embed with a stubbed deterministic
  embedder → ask an in-corpus question: the answer cites the right topic's items
- Ask an out-of-corpus question: the answer declines and the fake records **zero** `stream` calls
- Event ordering strict in the response bytes: `token*` → `citations` → `done`, skipping `:` comments.
  Assert order in the byte stream, never wall-clock interleaving — `TestClient` buffers
- A mocked mid-stream failure emits `error` with no `citations` and no `done`, and the stream closes
  cleanly. This test is meaningful only because `raise_server_exceptions=True` would surface an
  escaped exception as a raise — it passes only if the generator swallows correctly
- Runtime assertions on the request kwargs, stronger than the ACs' greps:
  `model == "claude-haiku-4-5"` and `not {"temperature", "top_p", "top_k"} & kwargs.keys()`
- `GET /chat/conversations/{id}` replays messages in `sequence` order across two turns
- Note: existing `client` fixtures build `TestClient(app)` without a `with` block, so the lifespan
  never runs. Fine here — retrieval does not depend on the HNSW index

**Frontend:**

- Streaming render: tokens appear incrementally, not as one flush
- Citation chip click-through reveals the source feedback item
- Error-state render when the stream emits `error`
- The reader skips `:` keepalive comment lines

**End-to-end (manual):**

- Real run against a ~1000-row dataset; paste one good and one deliberately out-of-scope Q&A into the
  PR description
- Record token usage and latency for the good Q&A
- Record the observed hallucinated-index and empty-citation rates, and the empirical basis for the
  `CHAT_MAX_DISTANCE` value

## Definition of Done

- All acceptance criteria met; `uv run pytest` and `pnpm --filter client build` pass
- The `fastapi.sse` availability probe run and the chosen transport path recorded in the PR
- `ANTHROPIC_CHAT_MODEL` default is `claude-haiku-4-5`; model-literal grep clean over `app/api/`,
  `app/insights/`, `app/clustering/`, `app/embeddings/`
- `client/src/api/` regenerated and committed after the backend routes land
- Sample Q&A transcripts, token usage, and latency in the PR description
- Delivered on the single branch `feat/server/chat-with-data` with separately-scoped commits
  (`feat(server): …` for the backend, `feat(client): …` for the panel, `refactor(api): …` for the
  regenerated client). This supersedes the PRD's two-PR Definition of Done
- Follow-ups filed, not fixed here: `summarizer.py:255`'s `temperature=1` (breaks with a 400 the day
  `ANTHROPIC_SUMMARIZATION_MODEL` points at Sonnet 5); `index.py:44`'s non-atomic `_index`/`_labels`
  publish (a torn read from the background embedding thread returns wrong UUIDs silently);
  `summarizer._sample_cluster_items`'s per-item `count_tokens` round-trip
