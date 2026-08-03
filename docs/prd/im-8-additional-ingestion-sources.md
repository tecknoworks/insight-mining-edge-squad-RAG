# IM-8 — Additional ingestion sources (Zendesk, Intercom, app store APIs)

**Type:** Epic (ships as one connector framework + one connector per sub-ticket)
**Epic:** Ingestion **Priority:** P2
**Estimate:** 8 points for the framework + 5 points per connector
**Depends on:** IM-1, IM-7
**Branch:** `feat/server/ingestion-connector-framework`, then one branch per connector

## Context

CSV upload is a manual, point-in-time action. Teams live in Zendesk, Intercom, and the app stores,
and want feedback to arrive continuously. This epic generalises ingestion from "parse an uploaded
file" to "pull from a source on a schedule", without duplicating the validation and persistence
work IM-1 already does.

**Do not build all connectors at once.** Ship the framework plus **Zendesk** first, prove the
abstraction survives contact with a second provider by adding **Intercom**, then decide whether the
app stores are worth the effort.

## Goal

A connector interface such that adding a new feedback source means implementing one class and
registering it — with credentials stored encrypted, syncs running incrementally from a cursor, and
every source normalising into the same `feedback_items` shape the CSV path already writes.

## Scope

**In scope**

- Connector abstraction + registry in `app/ingestion/connectors/`.
- `connections` and `sync_runs` tables; encrypted credential storage.
- Connect / list / sync-now / disconnect endpoints, org-scoped per IM-7.
- Incremental sync with a persisted cursor and deduplication.
- Scheduled background sync.
- Sub-ticket per provider: Zendesk → Intercom → (decide) App Store / Google Play.

**Out of scope**

- Two-way sync. This is read-only ingestion; Insight Miner never writes back to Zendesk.
- Real-time webhooks. Poll on a schedule; note webhooks as a future enhancement.
- Building any provider's OAuth consent UI beyond what the connector needs.

## Technical approach

- **The canonical shape does not change.** Every connector maps its provider's payload onto the
  existing data contract: `feedback_text` (required), `date`, `source`, `customer_id`. `source` is
  set to the provider name (`"zendesk"`, `"intercom"`, `"app_store"`). Providers must reuse IM-1's
  validation and persistence code rather than writing their own insert path — if that requires
  refactoring IM-1's parser to separate "read rows" from "validate and persist rows", do that
  refactor as the first commit of the framework PR.
- **Interface.** A `FeedbackConnector` protocol: `test_connection()`, `fetch_since(cursor) ->
AsyncIterator[RawFeedbackRecord]`, and `next_cursor(records)`. Registry maps a provider key to an
  implementation. Keep it a dict-based registry; do not build plugin discovery.
- **Credentials.** Encrypt at rest with a key from `CONNECTOR_ENCRYPTION_KEY` (required, no
  default), using Fernet or equivalent authenticated encryption. **Credentials are never returned by
  any endpoint** — not even masked-but-decryptable. `GET /connections` returns provider, status,
  last sync time, and an account label only.
- **Incremental sync.** Persist a per-connection cursor (Zendesk: `updated_at` watermark; Intercom:
  its pagination/`updated_at` scheme; app stores: review page cursor). Store a stable
  `external_id` per record and enforce a unique constraint on
  `(connection_id, external_id)` so a re-sync updates rather than duplicates.
- **Rate limits.** Every one of these providers rate-limits aggressively. Respect `Retry-After`,
  back off exponentially, and make a sync resumable — a sync interrupted by a rate limit must
  continue from its last committed cursor, not restart.
- **Scheduling.** `apscheduler` in-process, interval-based per connection
  (`CONNECTOR_SYNC_INTERVAL_MINUTES`, default 60). **Note the constraint explicitly in the spec:**
  in-process scheduling does not survive multiple app instances and will need a real job runner
  before horizontal scaling. Do not introduce Celery/Redis/Docker for this ticket.
- **Downstream chaining.** A completed sync leaves new `feedback_items` with `embedding IS NULL`.
  Trigger the IM-2 embedding job for the affected dataset at the end of a successful sync so the new
  data becomes searchable without manual intervention. Re-clustering stays manual — it changes
  existing cluster IDs and should be a deliberate act.

## API contract

```
GET    /ingestion/connectors                        → 200 available providers + required credential fields
POST   /ingestion/connections                       → 201 { provider, credentials, dataset_id? }
                                                       (validates credentials before persisting)
GET    /ingestion/connections                       → 200 list (never includes credentials)
POST   /ingestion/connections/{id}/sync             → 202 SyncRun
GET    /ingestion/connections/{id}/syncs            → 200 sync history
DELETE /ingestion/connections/{id}                  → 204 (revokes stored credentials)
```

## New configuration

`CONNECTOR_ENCRYPTION_KEY` (**required, no default**), `CONNECTOR_SYNC_INTERVAL_MINUTES`
(default `60`), `CONNECTOR_MAX_RECORDS_PER_SYNC` (default `10000`).

## Acceptance criteria — framework

1. Adding a new provider requires implementing `FeedbackConnector` and adding one registry entry —
   with no changes to the API layer, the persistence layer, or the scheduler. Demonstrated by the
   Zendesk and Intercom connectors sharing 100% of the sync orchestration code.
2. Records from every connector land in `feedback_items` in the same shape as CSV-ingested rows,
   with `source` set to the provider key and `date`/`customer_id` populated when the provider
   supplies them.
3. Connectors reuse IM-1's validation and persistence path; there is exactly one code path that
   writes `feedback_items`.
4. Credentials are encrypted at rest and **never** appear in any API response, log line, or
   exception message. A test greps captured logs during a failing sync to prove it.
5. The app fails to start when `CONNECTOR_ENCRYPTION_KEY` is unset.
6. `POST /ingestion/connections` validates credentials against the provider before persisting, and
   returns **400** with a clear message on invalid credentials.
7. A second sync fetches only records changed since the stored cursor, and re-syncing an overlapping
   window updates existing rows instead of creating duplicates (enforced by the
   `(connection_id, external_id)` unique constraint).
8. A `429` with `Retry-After` is honoured; a sync interrupted by rate limiting resumes from its last
   committed cursor.
9. A sync that fails partway persists the records it already committed, records the failure on the
   `sync_runs` row with a useful message, and does not advance the cursor past uncommitted records.
10. Scheduled sync runs at `CONNECTOR_SYNC_INTERVAL_MINUTES` per connection and is skipped if the
    previous run for that connection is still in flight.
11. A successful sync that added new items triggers the IM-2 embedding job for the affected dataset.
12. All connection endpoints are org-scoped per IM-7; another org's connection ID returns **404**.
13. `DELETE` revokes and deletes the stored credentials, not just the connection row.
14. `client/src/api/` regenerated and committed.

## Acceptance criteria — per connector sub-ticket

15. **Zendesk:** ingests ticket comments (or the configured ticket field), maps requester to
    `customer_id`, ticket creation/update time to `date`, and uses the incremental tickets export
    endpoint for cursoring.
16. **Intercom:** ingests conversation parts, maps contact to `customer_id`, and cursors on the
    provider's updated-at scheme.
17. **App Store / Google Play:** ingests reviews with rating preserved (extend the data contract with
    a nullable `rating` column if and only if this connector ships — do not add the column
    speculatively). Note in the spec that these APIs expose a limited review history window.

## Test plan

- Unit per connector, against **recorded fixture payloads** (VCR-style or committed JSON) — no live
  API calls in CI: mapping to the canonical shape; cursor extraction; pagination; rate-limit
  handling.
- Framework tests: dedup via the unique constraint; partial-failure cursor safety; scheduler skips
  overlapping runs; embedding job triggered after a successful sync.
- Security: credentials absent from all responses; credentials absent from logs during a forced
  failure; cross-org connection access returns 404.
- Manual, per connector: connect a real sandbox account, run a sync, confirm the items appear and
  flow through embedding → clustering → summarization end to end. Attach counts to the PR.
- Run `/security-review` on the framework branch (it introduces credential storage).

## Definition of done

Framework PR merged first, then one PR per connector. `/security-review` run on the framework PR.
`README.md` Core Features table updated to mention connector-based ingestion once the first
connector ships.
