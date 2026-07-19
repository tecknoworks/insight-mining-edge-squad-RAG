# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

The **skeleton is scaffolded**. On disk: a root pnpm workspace (`package.json`, `pnpm-workspace.yaml`), a FastAPI backend under `server/` (uv-managed, `/health` endpoint, config + DB wiring, Alembic ready, module stubs for each pipeline stage), and a Vite/React/TypeScript frontend under `client/` (with `src/api/` generated from the backend's OpenAPI schema). `pnpm dev` boots both; `pnpm --filter client generate:api` regenerates the typed client.

**No pipeline logic exists yet** — `app/ingestion/`, `app/embeddings/`, `app/clustering/`, `app/insights/` are documented stubs with no implementation, and no ORM models or migrations are authored. Each pipeline stage is built later via the Spec-Driven Design loop (`/spec-plan` → sign-off → `/spec-implement`). There is **no Docker**: Postgres (with pgvector) is developer-provided locally and reached via `DATABASE_URL`.

See `CONTRIBUTING.md` for branch naming, merge strategy, and commit message conventions. Two complementary mechanisms keep them applied: **git hooks enforce** (block non-conforming commits) and **project-local skills author** (help you and the team produce conforming branches/commits/PRs in the first place).

### Enforcement — git hooks (husky + lint-staged + commitlint)

`CONTRIBUTING.md`'s conventions are enforced by git hooks, installed automatically on `pnpm install` (the root `prepare` script runs `husky`):

- **`.husky/commit-msg`** runs commitlint against `commitlint.config.cjs` — the message must be `<type>(<scope>): <description>` with `<scope>` present and one of `server`/`client`/`root`/`api`.
- **`.husky/pre-commit`** runs lint-staged (`.lintstagedrc.json`) — prettier on staged JS/TS/JSON/MD/YAML, ruff on staged `server/**/*.py`.

### Authoring — git workflow skills (shared with the team)

Three project-local skills under `.claude/skills/` help produce conforming git operations rather than relying on everyone to remember the rules. They are **kept intentionally** (shared team tooling), not retired — they complement the hooks: the skills get the branch/commit/PR right up front, the hooks are the safety net that rejects anything that slips through.

- **`/git-branch`** — creates a branch named `<type>/<scope>/<short-desc>`, picking type/scope from the allowed lists.
- **`/git-commit`** — stages relevant files and writes a scoped Conventional Commit (`<type>(<scope>): <description>`) with a required, valid scope.
- **`/git-pr`** — opens a PR with a Conventional-Commits-style title and enforces the squash-and-merge-only policy.

Prefer these over freehand `git branch`/`git commit`/`gh pr create` so history stays consistent regardless of who (or what) is committing. Keep the two mechanisms in sync — if the allowed types/scopes in `CONTRIBUTING.md` change, update both `commitlint.config.cjs` and the skills.

## Workflow: Spec-Driven Design

Feature work follows **Spec-Driven Design (SDD)**: before writing implementation code, produce a spec — requirements, interfaces/API shapes, data contracts, and acceptance criteria — and get sign-off, then build to the spec. This matters especially while the repo is pre-scaffolding: pin design decisions down in a spec rather than improvising them during implementation.

## What Insight Miner Does

Turns large volumes of raw customer feedback (support tickets, NPS/survey free-text, app reviews) into actionable themes. The pipeline is the core mental model:

```
CSV Upload → Parse & Clean → Generate Embeddings → Semantic Clustering → Claude Summarization → Dashboard + Chat
```

Each stage maps to a planned backend module (see below). The defining choice is **semantic clustering over keyword rules**: feedback is grouped by meaning via vector embeddings, so "can't pay" and "checkout failed" land in the same theme. Claude then labels and summarizes each cluster, and a chat interface answers questions grounded in the feedback corpus (RAG over the same embeddings).

## Planned Architecture

Root-level **pnpm workspace** (`package.json` + `pnpm-workspace.yaml`, single root `pnpm-lock.yaml`) wrapping a Python backend and a React frontend — not two unrelated projects sharing a git repo:

- `server/` — FastAPI backend. Route handlers in `app/api/`, and the pipeline split into modules that mirror the stages above: `app/ingestion/` (CSV parse/validate), `app/embeddings/` (vectorization), `app/clustering/` (unsupervised grouping — HDBSCAN or k-means), `app/insights/` (Claude summarization + chat). Config in `app/core/`, Pydantic schemas / DB models in `app/models/`. Dependencies managed with **uv** — `pyproject.toml` + `uv.lock` only; do not add a `requirements.txt` (two dependency files falling out of sync is the failure mode being avoided). DB migrations live in `server/alembic/`.
- `client/` — React + TypeScript + Vite. `src/store/` holds React Context providers + hooks for app-wide state. Visualization is a cluster/scatter map sized by theme volume.
- **No `shared/` folder.** Crossing the Python/TypeScript boundary with hand-maintained shared types drifts out of sync. Instead, `client/src/api/` is generated from the backend's OpenAPI schema via `openapi-ts` — treat it as generated code, never hand-edit it, and regenerate (`pnpm --filter client generate:api`) whenever backend routes/schemas change.

When adding a pipeline feature, respect the module boundaries: keep embedding/clustering logic out of route handlers, and put Claude prompt logic in `app/insights/`.

## Anthropic / Claude Usage

Claude is used in two places — **cluster summarization** (batch: label a theme + pick representative quotes) and **chat-with-data** (RAG: answer over retrieved feedback). Before writing any Claude API call, embedding call, or model-selection code, consult the `claude-api` skill for current model IDs, pricing, and patterns rather than relying on memory. Requires `ANTHROPIC_API_KEY` in `server/.env`.

Which model backs each stage is a **system configuration decision, not application logic** — see `.env.local` / `server/.env`:

- `ANTHROPIC_SUMMARIZATION_MODEL` (default `claude-haiku-4-5`) — cluster summarization
- `ANTHROPIC_CHAT_MODEL` (default `claude-sonnet-5`) — chat-with-data

Never hardcode a model ID in application code; always read one of these two env vars. No runtime model switching and no UI model-selection dropdown — changing a model means editing the env var and redeploying. Keep `app/insights/` and any client code agnostic to which model string is configured.

## Commands

Root workspace install (once) — also installs the husky git hooks via `prepare`:

```bash
pnpm install                      # installs the JS/TS workspace (client/) per pnpm-workspace.yaml
```

Run both apps concurrently from the repo root (no `cd`-ing into `server/`/`client/`):

```bash
pnpm dev                          # backend on :8000 (uvicorn --reload) + frontend on :5173 (vite)
```

Backend only (`cd server`) — requires a local Postgres reachable via `DATABASE_URL`:

```bash
uv sync                           # installs deps from pyproject.toml / uv.lock, creates .venv automatically
uv run alembic upgrade head       # apply DB migrations (no migrations authored yet — chain is a no-op)
uv run uvicorn app.main:app --reload    # runs on :8000
uv run pytest                     # runs the backend test suite
```

Frontend only (`cd client`) — uses **pnpm** (9+), not npm:

```bash
pnpm generate:api                 # regenerate client/src/api/ from the backend's OpenAPI schema (backend must be running)
pnpm dev                          # runs on :5173, expects API at :8000
pnpm build                        # typecheck (tsc -b) + production build
```

## Data Contract

CSV ingestion is the entry point. Only `feedback_text` is required; `date`, `source`, and `customer_id` are optional. Preserve these optional fields through the pipeline where present — `source` and `date` drive filtered/temporal analysis ("what are people saying about checkout _this month_"), and `customer_id` traces feedback back to accounts.
