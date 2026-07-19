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
│   ├── alembic/            # DB migrations (SQLAlchemy models → PostgreSQL schema)
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
├── docker-compose.yml
└── README.md
```

**Suggested stack** (adjust as the project evolves):

- **Backend**: Python, FastAPI, Pydantic — dependencies managed with `uv` (single `pyproject.toml` + `uv.lock`, no `requirements.txt`)
- **Embeddings & Clustering**: `sentence-transformers` or Claude/Anthropic embeddings API, `scikit-learn` / `hdbscan`
- **AI Summaries & Chat**: Anthropic Claude API
- **Storage**: PostgreSQL (+ `pgvector`) or a dedicated vector store, with Alembic migrations under `server/alembic/`
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

> These steps assume a standard FastAPI + Vite React setup. Update once the actual scaffolding is in place.

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 18+
- pnpm 9+ (`npm install -g pnpm` if you don't have it yet)
- An Anthropic API key

### Workspace setup (root)

```bash
pnpm install   # installs the JS/TS workspace (client/) from the root pnpm-workspace.yaml
```

### Backend

```bash
cd server
uv sync                        # installs deps from pyproject.toml / uv.lock, creates .venv automatically
cp .env.example .env           # add ANTHROPIC_API_KEY, ANTHROPIC_SUMMARIZATION_MODEL, ANTHROPIC_CHAT_MODEL, and DB connection string
uv run alembic upgrade head    # apply DB migrations
uv run uvicorn app.main:app --reload
```

### Frontend

```bash
cd client
pnpm generate:api   # regenerate the typed API client from the backend's OpenAPI schema (requires the backend running)
pnpm dev
```

The frontend will run on `http://localhost:5173` and expect the API at `http://localhost:8000` (configurable via `.env`).

### Run everything from the root

Once the root workspace scripts land, `pnpm dev` from the repo root starts the FastAPI backend (via `uv run uvicorn ...`) and the Vite dev server concurrently — no need to `cd` into `server/` or `client/` separately.

## AI Model Configuration

Which Claude model powers each AI-driven stage is a **system configuration decision**, not an application concern. Two env vars (see `.env.local`, or `server/.env` once backend scaffolding lands) select the model per stage:

| Env var                         | Used by                                                                  | Default                                                                  |
| ------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `ANTHROPIC_SUMMARIZATION_MODEL` | Batch cluster summarization (label a theme + pick representative quotes) | `claude-haiku-4-5` — high-volume batch task, cheapest tier is sufficient |
| `ANTHROPIC_CHAT_MODEL`          | Chat-with-data (RAG over the feedback corpus)                            | `claude-sonnet-5` — interactive, needs stronger reasoning                |

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
| **specs-plan**     | `/specs-plan`     | Generates a new spec file under `/specs` for a feature — goal, acceptance criteria, test plan.    |
| **spec-implement** | `/spec-implement` | Builds to an approved spec: touches only the files it lists and verifies its acceptance criteria. |

Typical flow: `/specs-plan <feature>` to draft the spec → review and sign off → `/spec-implement <feature>` to build it.

## Contributing

This project is in early development. Issues and PRs are welcome once the initial scaffolding lands.

## License

TBD
