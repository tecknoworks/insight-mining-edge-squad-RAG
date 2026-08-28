"""Cluster routes — semantic grouping of feedback.

Thin handlers only. Clustering logic belongs in ``app.clustering`` and
Claude summarization in ``app.insights``.
"""

import uuid
from typing import Any

from anthropic import Anthropic
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.clustering.service import run_clustering, should_cluster
from app.core.config import get_settings
from app.core.db import get_db
from app.insights.summarizer import get_or_generate_cluster_summary
from app.models.db import Cluster, ClusterAssignment, ClusteringRun, Dataset, FeedbackItem
from app.models.schemas import (
    ClusterAssignmentPoint,
    ClusterItemPage,
    ClusterItemsPage,
    ClusterMap,
    ClusterSummary,
    ClusterSummaryResponse,
)
from app.models.schemas import (
    ClusteringRun as ClusteringRunSchema,
)


class ClusteringRunRequest(BaseModel):
    """Request body for POST /clusters/runs."""

    dataset_id: uuid.UUID
    mode: str = "incremental"
    params: dict[str, Any] | None = None

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.post("/runs", response_model=ClusteringRunSchema, status_code=status.HTTP_202_ACCEPTED)
def start_clustering_run(
    request: ClusteringRunRequest,
    db: Session = Depends(get_db),
) -> ClusteringRun:
    """Start a clustering run for a dataset.

    Args:
        request: Request body with dataset_id, mode, and optional params.

    Returns:
        202 with the ClusteringRun.
        404 if dataset not found.
        409 if dataset has no embeddings.
    """
    dataset = db.get(Dataset, request.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")

    settings = get_settings()
    params = request.params or {}

    # Check if clustering should run
    threshold = settings.clustering_incremental_threshold
    if not should_cluster(db, request.dataset_id, request.mode, threshold):
        # Incremental mode and threshold not met — return current run
        current_run = db.execute(
            select(ClusteringRun)
            .where(ClusteringRun.dataset_id == request.dataset_id, ClusteringRun.is_current)
        ).scalar_one_or_none()
        if current_run:
            return current_run
        # No current run, fall through to execute clustering

    # Prepare algorithm parameters with defaults
    algo_params = {
        "min_cluster_size": params.get("min_cluster_size", settings.clustering_min_cluster_size),
        "min_samples": params.get("min_samples", settings.clustering_min_samples),
        "reduced_dimensions": params.get(
            "reduced_dimensions", settings.clustering_reduced_dimensions
        ),
        "random_seed": params.get("random_seed", settings.clustering_random_seed),
    }

    # Execute clustering
    try:
        run = run_clustering(db, request.dataset_id, algo_params, get_settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return run


@router.get("/runs/{run_id}", response_model=ClusteringRunSchema)
def get_clustering_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> ClusteringRun:
    """Fetch a clustering run by ID."""
    run = db.get(ClusteringRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return run


@router.get("", response_model=list[ClusterSummary])
def list_clusters(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[Cluster]:
    """List clusters from the current run for a dataset, ordered by size descending."""
    run = db.execute(
        select(ClusteringRun)
        .where(ClusteringRun.dataset_id == dataset_id, ClusteringRun.is_current)
    ).scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no clustering run found")

    clusters = list(
        db.execute(
            select(Cluster)
            .where(Cluster.run_id == run.id)
            .order_by(Cluster.item_count.desc())
        ).scalars().all()
    )

    return clusters


@router.get("/{cluster_id}/items", response_model=ClusterItemsPage)
def list_cluster_items(
    cluster_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ClusterItemsPage:
    """List feedback items in a cluster, paginated."""
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cluster not found")

    items = db.execute(
        select(FeedbackItem)
        .join(
            ClusterAssignment,
            and_(
                ClusterAssignment.feedback_item_id == FeedbackItem.id,
                ClusterAssignment.cluster_id == cluster_id,
            ),
        )
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return ClusterItemsPage(
        items=[ClusterItemPage.model_validate(item) for item in items]
    )


@router.get("/{cluster_id}/summary", response_model=ClusterSummaryResponse)
def get_cluster_summary(
    cluster_id: uuid.UUID,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Get or generate a Claude summary for a cluster.

    Returns a cached summary if available and not forced; otherwise generates
    a new one via Claude (label, summary text, representative quotes) and caches it.

    Args:
        cluster_id: Cluster to summarize.
        force: If true, bypass cache and regenerate.
        db: Database session.

    Returns:
        200 with ClusterSummaryResponse (cluster_id, label, summary, quotes, cached_at).
        404 if cluster not found.
        503 if summarization failed (Claude API error or validation failure).
    """
    settings = get_settings()

    # Verify cluster exists
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cluster not found")

    # Initialize Anthropic client
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Anthropic API key not configured",
        )
    client = Anthropic(api_key=settings.anthropic_api_key)

    # Generate or retrieve cached summary
    try:
        result = get_or_generate_cluster_summary(db, cluster_id, settings, client, force=force)
    except ValueError as exc:
        error_detail = str(exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail,
        ) from exc
    except Exception as exc:
        error_detail = f"{type(exc).__name__}: {str(exc)}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail,
        ) from exc

    return result


@router.get("/map", response_model=ClusterMap)
def get_cluster_map(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ClusterMap:
    """Get the cluster map for visualization — all points + cluster metadata."""
    run = db.execute(
        select(ClusteringRun)
        .where(ClusteringRun.dataset_id == dataset_id, ClusteringRun.is_current)
    ).scalar_one_or_none()

    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no clustering run found")

    # Fetch all assignments for this run
    assignments = db.execute(
        select(ClusterAssignment).where(ClusterAssignment.run_id == run.id)
    ).scalars().all()

    points = [
        ClusterAssignmentPoint(
            feedback_item_id=a.feedback_item_id,
            cluster_id=a.cluster_id,
            x=a.x,
            y=a.y,
        )
        for a in assignments
    ]

    # Fetch clusters with their counts
    clusters = db.execute(
        select(Cluster).where(Cluster.run_id == run.id).order_by(Cluster.item_count.desc())
    ).scalars().all()

    cluster_summaries = [
        ClusterSummary(
            id=c.id,
            cluster_index=c.cluster_index,
            item_count=c.item_count,
            label=c.label,
        )
        for c in clusters
    ]

    return ClusterMap(points=points, clusters=cluster_summaries)
