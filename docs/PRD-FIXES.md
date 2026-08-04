# PRD Refinements — August 3, 2026

This document summarizes the updates made to the Insight Miner PRDs to fix architectural ambiguities and ensure implementation clarity. All tickets are now ready for engineering.

## Critical Fixes (Architectural)

### IM-2: Embedding Provider Clarified

- **Issue:** Spec referenced "Voyage AI" but architecture uses open-source `sentence-transformers`.
- **Fix:** Removed all Voyage references. Spec now explicitly uses `all-MiniLM-L6-v2` (384 dims).
- **API Response:** Updated `EmbeddingJobStatus` schema with correct model name and dimensions.
- **Impact:** IM-3, IM-6 now have clear embedding behavior to depend on.

### IM-6: Database Engine Corrected

- **Issue:** Spec mentioned pgvector (`<=>` operator), but database is SQLite.
- **Fix:** Retrieval now uses in-memory HNSW index (built in IM-2), not database vectors.
  - Query embedding → HNSW search → SQL fetch with org/source/date filters
  - Clarified that filters must be SQL predicates (not post-filtering) to respect authorization.
- **Impact:** Engineers know retrieval happens in-memory, not via Postgres syntax.

### IM-6: AI Model Aligned with Cost Strategy

- **Issue:** Spec defaulted to Claude Sonnet 5; contradicts cost-optimized Haiku strategy.
- **Fix:** Changed default to `claude-haiku-4-5` per `CLAUDE.md`.
- **Clarification:** Removed Sonnet 5–specific constraints (no `temperature`/`top_p`/`top_k`).
- **Escape hatch:** Documented that if Haiku reasoning is insufficient, upgrade to Sonnet (raise ticket).

### IM-6: SSE Event Ordering Specified

- **Issue:** Spec listed events but didn't define order or error handling.
- **Fix:** Strict order now specified: `token*` → `citations` (once) → `done` (once).
  - Error interrupts stream without `done` or `citations`.
  - Documented in API contract with examples.
- **Impact:** Client and server implementations won't collide on stream structure.

### IM-3: UMAP Decision Locked In

- **Issue:** Spec said "if UMAP is problematic, use TruncatedSVD" — left as a decision point.
- **Fix:** **Committed to UMAP** (chosen over SVD for better structure preservation).
  - Documented the constraint: disk/memory footprint exists, but acceptable for the stage.
  - If real-world use proves otherwise, raise a follow-up ticket.
- **Impact:** Implementation can proceed without hedging.

---

## Design Clarity Fixes

### IM-7: Retrofit Checklist Added

- **New:** Added a table showing per-stage changes:
  - What tables get `organization_id`.
  - What endpoints change and how.
  - Query patterns (correct scoping via ForeignKey chains, anti-patterns to avoid).
- **Impact:** Engineers building IM-7 won't have to guess where tenancy boundaries go.

### IM-8: Scheduler Constraint Front-and-Center

- **Moved:** Scaling ceiling (in-process ≠ horizontal) now in **Scope/Constraint** section (not buried).
  - Bold warning: "Before deploying to multiple instances, replace with a real job runner."
  - Reference to README.md for documentation.
- **Impact:** Teams won't be surprised when load-balancing fails.

### IM-8: Per-Connection Tuning Added

- **New:** Each connection can override sync interval (`sync_interval_minutes`).
  - Default falls back to global `CONNECTOR_SYNC_INTERVAL_MINUTES`.
  - New `PATCH /ingestion/connections/{id}` endpoint to adjust without full reconnect.
- **Impact:** Operators can tune sync cadence per source without code or env-var changes.

### IM-1: CSV Column Matching Clarified

- **Clarified:** Column order does not matter; matching is by name.
  - Added examples: `Feedback_Text`, `feedback text` (with space) all work.
  - Whitespace-only cells become `NULL` (not empty strings).
- **Impact:** CSV parser is robust to real-world input variations.

### IM-4: Quote Length Limits Added

- **New:** Quotes truncated to max 500 chars (appends `…` if truncated).
  - Validation checks that truncated quotes are still valid substrings.
  - Test asserts `quote in feedback_item.text` for all quotes.
- **Impact:** Response payloads stay manageable; no surprise bloat from long feedback.

### IM-5: Keyboard Navigation Model Specified

- **Detailed:** Tab + arrow keys (↑/↓), Space/Enter to select.
  - Focus indicator always visible (no hidden outline).
  - Selection synced bidirectionally between list and chart.
  - Noise points included in list.
- **Impact:** Accessibility isn't left to chance; implementation has concrete interaction spec.

---

## Dependency Implications

| Ticket | Depends On | Now Clear Because                                                           |
| ------ | ---------- | --------------------------------------------------------------------------- |
| IM-2   | IM-1       | Model/dimension defaults locked in; no provider churn.                      |
| IM-3   | IM-2       | UMAP chosen; dimensionality reduction is deterministic.                     |
| IM-4   | IM-3       | Claude call pattern set (Haiku, no special params). Quote validation clear. |
| IM-5   | IM-3, IM-4 | Visual encoding stable; keyboard model specified.                           |
| IM-6   | IM-2       | HNSW retrieval path clear; Haiku model confirmed. SSE contract final.       |
| IM-7   | IM-1→IM-6  | Retrofit checklist unambiguous per stage. Query patterns explicit.          |
| IM-8   | IM-1, IM-7 | Scheduler constraint acknowledged. Per-connection tuning unblocks ops.      |

---

## For the Team

- **All PRDs are now implementation-ready.** No more architectural hedging.
- **Each ticket references CLAUDE.md for model config.** Stay consistent (Haiku throughout).
- **Acceptance criteria are tight.** Tests can be written directly from the spec.
- **Do not revert these fixes.** They reflect the architecture in README.md and CLAUDE.md.

If you discover a spec ambiguity during implementation (not here), raise it in the PR — don't guess.
