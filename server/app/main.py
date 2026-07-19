"""FastAPI application entry point.

Wires CORS and the API routers. The OpenAPI schema this app serves at
``/openapi.json`` is the source of truth for the frontend's generated client
(``pnpm --filter client generate:api``).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api import chat, clusters, health, ingestion
from app.core.config import get_settings

settings = get_settings()


def _unique_id(route: APIRoute) -> str:
    """Use the handler's function name as the OpenAPI operationId.

    Keeps the generated frontend client's function names readable (e.g.
    ``health()`` instead of ``healthHealthGet()``).
    """
    return route.name


app = FastAPI(
    title="Insight Miner API",
    version="0.0.0",
    description="Semantic customer feedback & insight mining pipeline.",
    generate_unique_id_function=_unique_id,
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
