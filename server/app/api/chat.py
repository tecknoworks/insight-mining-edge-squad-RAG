"""Chat-with-data routes (placeholder).

Endpoints for RAG-style questions over the feedback corpus land here. Retrieval
and Claude prompt logic belong in ``app.insights``, not in these handlers.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/chat", tags=["chat"])
