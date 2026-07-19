---
name: check-setup
description: Verify the Insight Miner monorepo is set up correctly — check system requirements, dependencies, env files, and DB connectivity, then attempt to boot both server and client. Use when onboarding, when `pnpm dev` fails, or to sanity-check the environment.
---

Verify the project is set up correctly and can boot. Work top to bottom; **do not skip ahead** — a later step assumes the earlier ones passed. For every problem, give the user the specific fix command (the bundled script already prints these) rather than a vague "check your setup".

## 1. Run the diagnostics script

Run the read-only doctor from the repo root:

```bash
bash .claude/skills/check-setup/check-setup.sh
```

It checks, in order, and prints `PASS` / `WARN` / `FAIL` with a fix hint on each non-green line:

1. **System requirements** — `node` (>= 18; `.nvmrc` pins 22), `pnpm` (>= 9), a Python 3.11+ interpreter, `uv`, and the optional `psql` client.
2. **Environment files** — `server/.env` (required; holds `ANTHROPIC_API_KEY`, `DATABASE_URL`, and the per-stage model vars).
3. **Installed dependencies** — root `node_modules`, the `client` workspace, husky git hooks, and `server/.venv` (with backend imports actually resolving).
4. **Database connectivity** — connects to `DATABASE_URL` and confirms the `pgvector` extension is enabled.

The script never mutates the repo or installs anything — it only inspects. It exits non-zero if any check **FAILs** (WARNs don't fail it).

## 2. Resolve findings, then re-run

Report the results grouped as **FAIL** (blocks boot) vs **WARN** (works, but should be fixed). For each FAIL, run or offer the exact fix the script printed. The common ones:

| Symptom                                            | Fix                                                                                                           |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Node too old / wrong version                       | `nvm install 22 && nvm use` (matches `.nvmrc`)                                                                |
| `pnpm` missing                                     | `corepack enable pnpm`                                                                                        |
| `uv` missing                                       | `curl -LsSf https://astral.sh/uv/install.sh \| sh`                                                            |
| `node_modules` / client deps / husky hooks missing | `pnpm install` (repo root — its `prepare` also installs the git hooks)                                        |
| `server/.venv` missing or backend imports fail     | `uv sync --project server`                                                                                    |
| `server/.env` missing                              | `cp server/.env.example server/.env`, then fill in `ANTHROPIC_API_KEY`                                        |
| Postgres unreachable                               | Start a local Postgres and create the DB/user in `DATABASE_URL` (no Docker in this repo — developer-provided) |
| `pgvector` not enabled                             | Connect to the DB and run `CREATE EXTENSION IF NOT EXISTS vector;`                                            |

After applying fixes, **re-run the script** until there are no FAILs. Confirm with the user before running any install command that changes their machine or the repo.

## 3. Attempt to boot the apps

Only once step 1 shows no FAILs. Boot the backend and frontend and confirm each actually comes up — don't just launch and assume success.

**Backend** (from `server/`):

```bash
uv run --project server uvicorn app.main:app --app-dir server
```

Verify it's serving by hitting the health endpoint in another shell:

```bash
curl -fsS http://localhost:8000/health && curl -fsS http://localhost:8000/openapi.json > /dev/null && echo OK
```

**Frontend** (from the repo root):

```bash
pnpm --filter client dev
```

Confirm Vite reports it's listening on `http://localhost:5173`.

**Both at once** — the normal dev command, which runs the two concurrently:

```bash
pnpm dev
```

When you run a server as a foreground process to test it, use a background run and stop it after you've confirmed it responds — never leave a dev server running when you hand control back to the user. If a boot fails, capture the actual error output and map it back to a step-1 check (e.g. a psycopg connection error → step 4 DB, a `ModuleNotFoundError` → `uv sync`, an Anthropic auth error → `ANTHROPIC_API_KEY` in `server/.env`).

## 4. Report

Give the user a short, honest summary: what passed, what you fixed, whether both apps booted (with the URLs — API `:8000`, health `:8000/health`, client `:5173`), and any remaining WARNs worth addressing later. If something is still broken, state exactly what and the next action — don't claim success it didn't reach.
