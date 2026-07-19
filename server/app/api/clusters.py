"""Cluster routes (placeholder).

Endpoints exposing discovered themes and their summaries land here. Clustering
logic belongs in ``app.clustering`` and Claude summarization in ``app.insights``.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/clusters", tags=["clusters"])
