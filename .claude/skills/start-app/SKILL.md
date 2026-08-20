---
name: start-app
description: Start the Insight Miner server and client for local development — the combined `pnpm dev` command plus how to run each side independently. Use when the user asks to start, run, launch, or boot the app/server/client, or wants the dev URLs.
---

## 1. Prerequisites

- If this is the first run (no `node_modules/` or `server/.venv/` yet), install once from the repo
  root: `pnpm install` (also installs the husky git hooks via `prepare`).
- `server/.env` must exist. If it's missing, copy it from the template:
  `cp server/.env.example server/.env`. Without it the backend will fail to start.
- If anything looks off before booting (missing deps, bad env, DB issues), run `/check-setup`
  first instead of guessing — it's a full environment diagnostic.

## 2. Start both (recommended)

From the repo root:

```bash
pnpm dev
```

This runs the backend and frontend concurrently (`concurrently`), with interleaved logs labeled
`server` (blue) and `client` (magenta):

- Backend — `uvicorn app.main:app --reload` on `http://localhost:8000`
- Frontend — `vite` on `http://localhost:5173`

Ctrl-C stops both.

## 3. Start only the server

```bash
cd server
uv run uvicorn app.main:app --reload
```

- The SQLite database file (`insight_miner.db`) is created automatically on startup if it doesn't
  exist.
- If dependencies changed, run `uv sync` first.
- If migrations are pending, run `uv run alembic upgrade head`.

## 4. Start only the client

```bash
cd client
pnpm dev
```

Runs on `http://localhost:5173` and expects the API already running at `http://localhost:8000`.

## 5. Verify it's up

- Backend health: `http://localhost:8000/health`
- Backend API docs: `http://localhost:8000/docs`
- Frontend: `http://localhost:5173`

## 6. If it won't start

Don't guess — run `/check-setup` to diagnose dependency, env-file, or DB connectivity issues.
