# Insight Miner

**Semantic Customer Feedback & Insight Mining**

Turn thousands of raw customer comments into clear, actionable themes. Insight Miner uses semantic search, clustering, and Claude-generated summaries so Product Managers, Customer Success teams, and Executives can understand what customers are saying without reading every ticket, review, and survey response by hand.

---

## Why

Feedback piles up faster than anyone can read it — support tickets, NPS comments, app store reviews, survey free-text. Important signals (a spike in "payment issues," a new "shipping delay" complaint) get lost in the noise. Insight Miner ingests that raw feedback and turns it into:

- **Themes**, automatically discovered via semantic clustering (not fragile keyword rules)
- **Summaries**, written by Claude, explaining what each theme means and why it matters
- **Answers**, via a chat interface that lets you ask questions directly against the feedback corpus

## Core Features

| Area                    | Description                                                                                                                             |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **Ingestion**           | Upload feedback via CSV. Each row is parsed, embedded, and stored for search and clustering.                                            |
| **Semantic Clustering** | Feedback is grouped by meaning, not exact wording, surfacing themes like "payment issues," "shipping delays," or "UI confusing."        |
| **Insight Summaries**   | Claude generates a plain-language summary for each cluster: what it's about, how big it is, and representative quotes.                  |
| **Chat with Data**      | Ask natural-language questions ("What are people saying about checkout this month?") and get answers grounded in the actual feedback.   |
| **Visualization**       | An interactive graphic (e.g. a cluster/scatter map) shows feedback groups and their relative size, so patterns are visible at a glance. |

## How It Works

```
CSV Upload → Parse & Clean → Generate Embeddings → Cluster (semantic) → Claude Summarization → Dashboard + Chat
```

1. **Ingest**: A CSV of feedback (e.g. `feedback_text`, `date`, `source`, `customer_id`) is uploaded through the frontend.
2. **Embed**: Each feedback item is converted into a vector embedding capturing its meaning.
3. **Cluster**: Embeddings are grouped using an unsupervised clustering algorithm (e.g. HDBSCAN or k-means), so feedback with similar meaning lands in the same theme — regardless of exact phrasing.
4. **Summarize**: Claude reads each cluster and generates a human-readable insight summary, theme label, and supporting examples.
5. **Explore**: The frontend visualizes clusters as a graphic (e.g. bubble/scatter chart sized by volume) and lets users chat with the underlying data for follow-up questions.

## Tech Stack

This is a **monorepo** with a Python backend and a React frontend.

```
insight-miner/
├── package.json            # Root workspace manifest — orchestration scripts (e.g. `pnpm dev` runs client + server concurrently)
├── pnpm-workspace.yaml     # Declares workspace members (client/, future packages/* if UI/state code is extracted)
├── pnpm-lock.yaml          # Single lockfile for the whole JS/TS workspace (root-level, not nested in client/)
├── server/                 # Python backend (FastAPI)
│   ├── app/
│   │   ├── api/            # Route handlers (ingestion, clusters, chat)
│   │   ├── core/           # Config, settings
│   │   ├── ingestion/      # CSV parsing & validation
│   │   ├── embeddings/     # Embedding generation
│   │   ├── clustering/     # Clustering logic
│   │   ├── insights/       # Claude-powered summarization & chat
│   │   ├── models/         # Pydantic schemas / DB models
│   │   └── main.py
│   ├── alembic/            # DB migrations (SQLAlchemy models → SQLite schema)
│   │   ├── versions/
│   │   └── env.py
│   ├── tests/
│   ├── pyproject.toml      # Single source of truth for deps + tool config (managed with uv)
│   └── uv.lock
├── client/                 # ReactJS frontend
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── store/          # React Context providers + hooks (app-wide state)
│   │   ├── api/            # Generated from the backend's OpenAPI schema via openapi-ts — do not hand-edit
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

> **No Docker, no hosted database.** SQLite is a single-file database created automatically on first run and reached via `DATABASE_URL`. Vector indexing is handled in-memory via `hnswlib`. No external services to provision.

**Suggested stack** (cost-optimized for low maintenance):

- **Backend**: Python, FastAPI, Pydantic — dependencies managed with `uv` (single `pyproject.toml` + `uv.lock`, no `requirements.txt`)
- **Database & Storage**: SQLite (single-file, auto-created on startup) with Alembic migrations under `server/alembic/`
- **Embeddings**: `sentence-transformers` (open-source, runs locally — zero API cost)
- **Vector Indexing**: `hnswlib` (in-memory HNSW, pure Python)
- **Clustering**: `scikit-learn` / `hdbscan` (incremental and on-demand modes supported)
- **AI Summaries & Chat**: Anthropic Claude API (Haiku model, cost-optimized; summaries cached and generated on-demand)
- **Frontend**: React, TypeScript, Vite
- **API Client**: Generated from FastAPI's OpenAPI schema via `openapi-ts` — see [Type Safety Across the Stack](#type-safety-across-the-stack) below
- **State Management**: React Context + hooks, under `client/src/store/`
- **Visualization**: Recharts / D3 / Plotly for the cluster graphic

### Type Safety Across the Stack

There is deliberately **no `shared/` folder**. A shared directory works well in an all-TypeScript monorepo, but crossing the Python/TypeScript boundary that way is painful — you cannot natively import Python types into TypeScript, so a hand-maintained `shared/` package tends to drift out of sync with the actual API shape.

Instead: FastAPI generates an OpenAPI schema automatically from the route handlers and Pydantic models in `server/app/`. `openapi-ts` consumes that schema to generate the entire typed client — request functions and TypeScript interfaces — directly into `client/src/api/`. This is a build step, not a hand-maintained package:

```bash
# with the backend running locally (schema served at /openapi.json)
pnpm --filter client generate:api
```

Run this whenever backend routes or schemas change, and commit the generated output so CI and other contributors don't need the backend running to build the frontend. Treat `client/src/api/` as generated code — never edit it by hand.

## Getting Started

> The skeleton is scaffolded and boots today. No pipeline logic is implemented yet — see the [Roadmap](#roadmap).

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 18+ (the repo pins 22 via `.nvmrc` — run `nvm use`)
- pnpm 9+ (`corepack enable pnpm`)
- An Anthropic API key (`ANTHROPIC_API_KEY` in `server/.env`)

That's it — SQLite and open-source embeddings have zero external dependencies.

### Quick start (recommended)

From the repo root:

```bash
pnpm install                       # installs the client workspace + husky git hooks (via the prepare script)
uv sync --project server           # creates server/.venv and installs backend deps
cp server/.env.example server/.env # then fill in ANTHROPIC_API_KEY (DATABASE_URL defaults to SQLite file)
uv run --directory server alembic upgrade head # apply DB migrations (chain is a no-op until migrations are authored)
pnpm dev                           # boots backend (:8000) + frontend (:5173) concurrently
```

`pnpm dev` runs `uv run uvicorn app.main:app --reload` and the Vite dev server together — no need to `cd` into `server/` or `client/`. On first run, the backend creates `server/insight_miner.db` (SQLite file) automatically. Verify the backend with `curl http://localhost:8000/health` (→ `{"status":"ok"}`).

### Running an app on its own

Backend only (`cd server`):

```bash
uv sync
uv run uvicorn app.main:app --reload   # http://localhost:8000
```

Frontend only (`cd client`, uses pnpm):

```bash
pnpm generate:api   # regenerate the typed API client from the backend's OpenAPI schema (backend must be running)
pnpm dev            # http://localhost:5173
pnpm build          # typecheck (tsc -b) + production build
```

The frontend defaults to the API at `http://localhost:8000`; override it by setting `VITE_API_URL` in `client/.env`. From the root you can also regenerate the client with `pnpm generate:api`.

### Verify the setup

Run the bundled doctor to check tooling, env files, dependencies, and DB connectivity, then attempt to boot both apps:

```bash
bash .claude/skills/check-setup/check-setup.sh
```

## AI Model Configuration

Which Claude model powers each AI-driven stage is a **system configuration decision**, not an application concern. Two env vars in `server/.env` (template: `server/.env.example`) select the model per stage:

| Env var                         | Used by                                                                 | Default                                                   |
| ------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------- |
| `ANTHROPIC_SUMMARIZATION_MODEL` | On-demand cluster summarization (label + representative quotes), cached | `claude-haiku-4-5` — cost-optimized for feedback analysis |
| `ANTHROPIC_CHAT_MODEL`          | Chat-with-data (RAG over the feedback corpus)                           | `claude-haiku-4-5` — cost-optimized; sufficient for Q&A   |

Rules that apply project-wide:

- **No hardcoded model IDs.** Every Claude API call reads its model from one of these two env vars — never a literal string in code.
- **No runtime model switching.** Changing a model means editing the env var and redeploying, not a settings toggle.
- **No UI dropdown for model selection.** This is an infra/ops decision, not a user-facing feature.
- **All layers stay model-agnostic.** Backend and frontend code must work unchanged regardless of which model string is configured.

## CSV Format

Minimum expected columns (exact schema to be finalized):

| Column          | Required | Description                                   |
| --------------- | -------- | --------------------------------------------- |
| `feedback_text` | ✅       | The raw customer feedback                     |
| `date`          | Optional | When the feedback was submitted               |
| `source`        | Optional | e.g. "support ticket," "app review," "survey" |
| `customer_id`   | Optional | For tracing feedback back to an account       |

## Roadmap

- [ ] CSV ingestion endpoint + validation
- [ ] Embedding pipeline
- [ ] Clustering service
- [ ] Claude-powered cluster summarization
- [ ] Cluster visualization component
- [ ] Chat-with-data endpoint + UI
- [ ] Auth / multi-tenant support
- [ ] Additional ingestion sources (Zendesk, Intercom, app store APIs)

## Development Workflow (Claude Code Skills)

This project follows **Spec-Driven Design (SDD)**: write a spec, get sign-off, then build to it. Two project-local Claude Code skills (under `.claude/skills/`) support this loop:

| Skill              | Command           | What it does                                                                                      |
| ------------------ | ----------------- | ------------------------------------------------------------------------------------------------- |
| **spec-plan**      | `/spec-plan`      | Generates a new spec file under `/specs` for a feature — goal, acceptance criteria, test plan.    |
| **spec-implement** | `/spec-implement` | Builds to an approved spec: touches only the files it lists and verifies its acceptance criteria. |

Typical flow: `/spec-plan <feature>` to draft the spec → review and sign off → `/spec-implement <feature>` to build it. Each pipeline stage (ingestion, embeddings, clustering, summarization, chat, visualization) is built this way.

Commit and branch conventions from [CONTRIBUTING.md](CONTRIBUTING.md) are enforced automatically by husky + lint-staged + commitlint (installed on `pnpm install`).

## Contributing

This project is in early development. The skeleton is scaffolded (`pnpm dev` runs both apps); pipeline features are built stage by stage via the SDD loop above. Issues and PRs welcome.

## License

TBD
