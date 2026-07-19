# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State

This repo is **pre-scaffolding**: git is initialized (`main` branch) and process docs (`CONTRIBUTING.md`, this file) exist, but there is no application code yet — no root `package.json`, `pnpm-workspace.yaml`, `server/`, or `client/`. Nothing in the tech stack, directory layout, or commands below exists on disk yet — they describe the *intended* design from the README. Treat the README's structure and command list as a proposal, not ground truth. When implementing, verify what actually exists before running any command, and update this file as real scaffolding lands.

See `CONTRIBUTING.md` for branch naming, merge strategy, and commit message conventions. Automated enforcement of those conventions (husky/lint-staged/commitlint) is deferred until the root `package.json` / pnpm workspace is scaffolded.

### Git Workflow Skills (stopgap for deferred hook enforcement)

Because husky/lint-staged/commitlint enforcement is deferred (see above), three project-local skills under `.claude/skills/` exist to keep `CONTRIBUTING.md`'s conventions applied consistently by hand until that tooling lands:

- **`/git-branch`** — creates a branch named `<type>/<scope>/<short-desc>`, picking type/scope from the allowed lists rather than guessing.
- **`/git-commit`** — stages relevant files and writes a scoped Conventional Commit message (`<type>(<scope>): <description>`), enforcing that scope is present and drawn from `server`/`client`/`root`/`api`.
- **`/git-pr`** — opens a PR with a Conventional-Commits-style title and reminds that this repo is squash-and-merge only.

Use these instead of freehand `git branch`/`git commit`/`gh pr create` so history stays consistent regardless of who (or what) is committing. Retire or fold these into the hook tooling once husky/lint-staged/commitlint are actually wired up — don't let both mechanisms diverge silently.

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

## Planned Commands (verify before use)

Root workspace install (once):
```bash
pnpm install                      # installs the JS/TS workspace (client/) per pnpm-workspace.yaml
```

Backend (`cd server`):
```bash
uv sync                           # installs deps from pyproject.toml / uv.lock, creates .venv automatically
uv run alembic upgrade head       # apply DB migrations
uv run uvicorn app.main:app --reload    # runs on :8000
```

Frontend (`cd client`) — uses **pnpm** (9+), not npm:
```bash
pnpm generate:api                 # regenerate client/src/api/ from the backend's OpenAPI schema (backend must be running)
pnpm dev                          # runs on :5173, expects API at :8000
```

Once root workspace scripts land, `pnpm dev` from the repo root should start both concurrently — no `cd`-ing into `server/`/`client/` separately.

## Data Contract

CSV ingestion is the entry point. Only `feedback_text` is required; `date`, `source`, and `customer_id` are optional. Preserve these optional fields through the pipeline where present — `source` and `date` drive filtered/temporal analysis ("what are people saying about checkout *this month*"), and `customer_id` traces feedback back to accounts.
