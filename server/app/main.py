"""FastAPI application entry point.

Wires CORS and the API routers. The OpenAPI schema this app serves at
``/openapi.json`` is the source of truth for the frontend's generated client
(``pnpm --filter client generate:api``).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from sqlalchemy import inspect as sa_inspect

from app.api import chat, clusters, health, ingestion
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.embeddings.index import build_index
from app.models.db import FeedbackItem

logger = logging.getLogger(__name__)

settings = get_settings()


def _unique_id(route: APIRoute) -> str:
    """Use the handler's function name as the OpenAPI operationId.

    Keeps the generated frontend client's function names readable (e.g.
    ``health()`` instead of ``healthHealthGet()``).
    """
    return route.name


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Warm the in-memory HNSW index from already-embedded rows before serving.

    Skipped when the schema has not been created yet. Warming used to run
    unconditionally, so starting the server against an un-migrated database
    aborted startup with a bare "no such table" traceback — which is exactly
    what a first-time setup hits, and it says nothing about what to do.
    """
    if not sa_inspect(engine).has_table(FeedbackItem.__tablename__):
        logger.warning(
            "Database schema not found — skipping vector-index warmup. "
            "Run `uv run alembic upgrade head` in server/ to create it."
        )
        yield
        return

    db = SessionLocal()
    try:
        build_index(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Insight Miner API",
    version="0.0.0",
    description="Semantic customer feedback & insight mining pipeline.",
    generate_unique_id_function=_unique_id,
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(ingestion.router)
app.include_router(clusters.router)
app.include_router(chat.router)
