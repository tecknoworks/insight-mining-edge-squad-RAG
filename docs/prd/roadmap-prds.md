# Insight Miner — Roadmap PRDs

Product Requirements Documents for every item on the [README Roadmap](../../README.md#roadmap).
Specifications are referenced below, organized by ticket. Copy a section into Jira as-is.

**Last updated:** 2026-08-03

---

## How engineers work these tickets

Every ticket below is built with the **Spec-Driven Design (SDD)** loop. Do not open an editor
before the spec is signed off.

1. `/spec-plan <feature>` — produces `/specs/<feature>.md` from this PRD. The PRD is the input;
   the spec is the contract. The spec must carry the exact sections in
   `.claude/skills/spec-plan/template.md`: Goal, Acceptance Criteria, Technical Approach,
   Edge Cases / Constraints, Files to Modify, Test Plan.
2. **Sign-off** — a human reviews the spec. Nothing gets built against a draft.
3. `/spec-implement <feature>` — builds to the signed-off spec. Touches only the files listed
   under "Files to Modify"; surfaces any file outside that list before changing it.

The "Acceptance Criteria" in each PRD are the **minimum** set that must appear in the spec.
The spec may add more; it may not drop any.

### Rules that apply to every ticket (do not restate them in the spec — just obey them)

| Rule                                                                                                                                           | Where it comes from                         |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Branch name is `<type>/<scope>/<short-desc>`; use `/git-branch`                                                                                | `CONTRIBUTING.md`                           |
| Commits are `<type>(<scope>): <description>` with a required scope of `server`/`client`/`root`/`api`; use `/git-commit`                        | `commitlint.config.cjs` (enforced by husky) |
| PRs are squash-merged only; use `/git-pr`, then `/git-sync`                                                                                    | `CONTRIBUTING.md`                           |
| Pipeline logic never lives in route handlers — routes orchestrate `app/ingestion/`, `app/embeddings/`, `app/clustering/`, `app/insights/`      | `CLAUDE.md`                                 |
| Claude prompt logic lives in `app/insights/` only                                                                                              | `CLAUDE.md`                                 |
| **No hardcoded model IDs.** Read `ANTHROPIC_SUMMARIZATION_MODEL` / `ANTHROPIC_CHAT_MODEL` from settings. No runtime switching, no UI dropdown. | `CLAUDE.md`, `README.md`                    |
| Backend deps go in `server/pyproject.toml` via `uv add`. **Never create a `requirements.txt`.**                                                | `CLAUDE.md`                                 |
| `client/src/api/` is generated. Never hand-edit. Run `pnpm generate:api` and commit the output whenever backend routes or schemas change.      | `README.md`                                 |
| Backend must pass `uv run ruff check`, `uv run mypy` (strict), `uv run pytest`                                                                 | `server/pyproject.toml`                     |
| Frontend must pass `pnpm --filter client build` (runs `tsc -b`)                                                                                | `client/package.json`                       |
| Postgres + pgvector is developer-provided via `DATABASE_URL`. **Do not add Docker or a compose file.**                                         | `README.md`                                 |
| Consult the `claude-api` skill before writing any Claude or embedding call                                                                     | `CLAUDE.md`                                 |

### Ticket index

| ID   | Title                                                            | File                                                                         | Depends on |
| ---- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------- | ---------- |
| IM-1 | CSV ingestion endpoint + validation                              | [im-1-csv-ingestion.md](im-1-csv-ingestion.md)                               | —          |
| IM-2 | Embedding pipeline                                               | [im-2-embedding-pipeline.md](im-2-embedding-pipeline.md)                     | IM-1       |
| IM-3 | Clustering service                                               | [im-3-clustering-service.md](im-3-clustering-service.md)                     | IM-2       |
| IM-4 | Claude-powered cluster summarization                             | [im-4-cluster-summarization.md](im-4-cluster-summarization.md)               | IM-3       |
| IM-5 | Cluster visualization component                                  | [im-5-cluster-visualization.md](im-5-cluster-visualization.md)               | IM-3, IM-4 |
| IM-6 | Chat-with-data endpoint + UI                                     | [im-6-chat-with-data.md](im-6-chat-with-data.md)                             | IM-2       |
| IM-7 | Auth / multi-tenant support                                      | [im-7-auth-multi-tenant.md](im-7-auth-multi-tenant.md)                       | IM-1       |
| IM-8 | Additional ingestion sources (Zendesk, Intercom, app store APIs) | [im-8-additional-ingestion-sources.md](im-8-additional-ingestion-sources.md) | IM-1, IM-7 |

IM-5 and IM-6 can run in parallel once IM-4 lands. IM-7 is a cross-cutting retrofit and is
cheapest to do **before** IM-8 and ideally before the dataset count grows.

---

## Appendix — dependencies this roadmap adds

Add with `uv add` (backend) / `pnpm --filter client add` (frontend). **Never create a
`requirements.txt`.**

| Ticket | Backend                                                                 | Frontend   |
| ------ | ----------------------------------------------------------------------- | ---------- |
| IM-1   | —                                                                       | —          |
| IM-2   | `voyageai`                                                              | —          |
| IM-3   | `scikit-learn`, `hdbscan`, `umap-learn`, `numpy`                        | —          |
| IM-4   | — (`anthropic` already present)                                         | —          |
| IM-5   | —                                                                       | `recharts` |
| IM-6   | `sse-starlette` (optional)                                              | —          |
| IM-7   | `pyjwt`, `argon2-cffi` (or `passlib[argon2]`)                           | —          |
| IM-8   | `cryptography`, `apscheduler`, `httpx` (already a dev dep — promote it) | —          |

## Appendix — configuration added across the roadmap

Every variable below must land in **both** `server/app/core/config.py` and `server/.env.example`.

| Variable                          | Ticket | Default                       |
| --------------------------------- | ------ | ----------------------------- |
| `MAX_UPLOAD_BYTES`                | IM-1   | `52428800`                    |
| `MAX_ROWS_PER_UPLOAD`             | IM-1   | `100000`                      |
| `MAX_REPORTED_ERRORS`             | IM-1   | `100`                         |
| `VOYAGE_EMBEDDING_MODEL`          | IM-2   | confirmed during `/spec-plan` |
| `EMBEDDING_DIMENSION`             | IM-2   | matches the model             |
| `EMBEDDING_BATCH_SIZE`            | IM-2   | `128`                         |
| `EMBEDDING_MAX_RETRIES`           | IM-2   | `5`                           |
| `CLUSTERING_MIN_CLUSTER_SIZE`     | IM-3   | `15`                          |
| `CLUSTERING_MIN_SAMPLES`          | IM-3   | `5`                           |
| `CLUSTERING_REDUCED_DIMENSIONS`   | IM-3   | `50`                          |
| `CLUSTERING_RANDOM_SEED`          | IM-3   | `42`                          |
| `SUMMARIZATION_CONCURRENCY`       | IM-4   | `4`                           |
| `SUMMARIZATION_MAX_SAMPLE_TOKENS` | IM-4   | `8000`                        |
| `SUMMARIZATION_MAX_TOKENS`        | IM-4   | `1024`                        |
| `CHAT_TOP_K`                      | IM-6   | `20`                          |
| `CHAT_MAX_DISTANCE`               | IM-6   | `0.6`                         |
| `CHAT_MAX_HISTORY_TOKENS`         | IM-6   | `20000`                       |
| `CHAT_MAX_TOKENS`                 | IM-6   | `8000`                        |
| `SECRET_KEY`                      | IM-7   | **none — required**           |
| `ACCESS_TOKEN_TTL_MINUTES`        | IM-7   | `15`                          |
| `REFRESH_TOKEN_TTL_DAYS`          | IM-7   | `30`                          |
| `PASSWORD_MIN_LENGTH`             | IM-7   | `12`                          |
| `CONNECTOR_ENCRYPTION_KEY`        | IM-8   | **none — required**           |
| `CONNECTOR_SYNC_INTERVAL_MINUTES` | IM-8   | `60`                          |
| `CONNECTOR_MAX_RECORDS_PER_SYNC`  | IM-8   | `10000`                       |

`ANTHROPIC_SUMMARIZATION_MODEL` and `ANTHROPIC_CHAT_MODEL` already exist and must not be duplicated,
renamed, or read from anywhere other than `app/core/config.py`.
