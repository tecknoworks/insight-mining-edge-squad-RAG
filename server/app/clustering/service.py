"""Clustering service — business logic for semantic clustering.

Handles incremental vs on-demand clustering, persistence, and noise handling.
"""

import uuid
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clustering.algorithms import HDBSCANClusterer
from app.models.db import Cluster, ClusterAssignment, ClusteringRun, FeedbackItem


def should_cluster(
    db: Session, dataset_id: uuid.UUID, mode: str, threshold: int
) -> bool:
    """Determine if clustering should run.

    Args:
        db: Database session.
        dataset_id: Dataset to cluster.
        mode: "on_demand" or "incremental".
        threshold: Number of new embeddings required to trigger incremental clustering.

    Returns:
        True if clustering should run, False if incremental check allows skipping.
    """
    if mode == "on_demand":
        return True

    # Incremental mode (default)
    current_run = db.execute(
        select(ClusteringRun)
        .where(ClusteringRun.dataset_id == dataset_id, ClusteringRun.is_current)
    ).scalar_one_or_none()

    if current_run is None:
        # No prior run, must cluster
        return True

    # Count un-embedded items added since the last run
    new_unembedded = db.execute(
        select(func.count(FeedbackItem.id)).where(
            FeedbackItem.dataset_id == dataset_id,
            FeedbackItem.embedding.is_(None),
            FeedbackItem.created_at > current_run.created_at,
        )
    ).scalar()

    return new_unembedded >= threshold


def run_clustering(
    db: Session,
    dataset_id: uuid.UUID,
    algorithm_params: dict[str, Any],
    settings_func: Any,
) -> ClusteringRun:
    """Execute clustering on a dataset.

    Args:
        db: Database session.
        dataset_id: Dataset to cluster.
        algorithm_params: Parameters for the clustering algorithm.
        settings_func: Callable returning settings object with random_seed.

    Returns:
        The created ClusteringRun.

    Raises:
        ValueError: If dataset has no embedded items.
    """
    settings = settings_func()

    # Load all embedded feedback items for the dataset
    embedded_items = db.execute(
        select(FeedbackItem)
        .where(
            FeedbackItem.dataset_id == dataset_id,
            FeedbackItem.embedding.isnot(None),
        )
        .order_by(FeedbackItem.id)
    ).scalars().all()

    if not embedded_items:
        raise ValueError("Dataset has no embedded items")

    # Extract vectors (BLOB → float32)
    vectors = np.array(
        [np.frombuffer(item.embedding, dtype=np.float32) for item in embedded_items],
        dtype=np.float32,
    )

    # Run clustering
    clusterer = HDBSCANClusterer(
        min_cluster_size=algorithm_params.get("min_cluster_size", 15),
        min_samples=algorithm_params.get("min_samples", 5),
        reduced_dimensions=algorithm_params.get("reduced_dimensions", 50),
        random_seed=algorithm_params.get("random_seed", settings.clustering_random_seed),
    )
    labels, x_2d, y_2d = clusterer.fit(vectors)

    # Mark previous current run as not current
    prev_run = db.execute(
        select(ClusteringRun)
        .where(ClusteringRun.dataset_id == dataset_id, ClusteringRun.is_current)
    ).scalar_one_or_none()
    if prev_run:
        prev_run.is_current = False

    # Create new run
    unique_labels = set(labels)
    noise_count = int((labels == -1).sum())
    cluster_count = len(unique_labels) - (1 if -1 in unique_labels else 0)

    run = ClusteringRun(
        dataset_id=dataset_id,
        algorithm="hdbscan",
        params=algorithm_params,
        random_seed=algorithm_params.get("random_seed", settings.clustering_random_seed),
        cluster_count=cluster_count,
        noise_count=noise_count,
        is_current=True,
    )
    db.add(run)
    db.flush()

    # Create clusters (exclude noise label -1)
    label_to_cluster: dict[int, Cluster] = {}
    for label in sorted(unique_labels):
        if label == -1:
            continue  # Noise, no cluster row needed
        cluster = Cluster(
            run_id=run.id,
            cluster_index=int(label),
            item_count=int((labels == label).sum()),
        )
        db.add(cluster)
        db.flush()
        label_to_cluster[label] = cluster

    # Create assignments
    for item, label, x, y in zip(
        embedded_items, labels, x_2d, y_2d, strict=True
    ):
        cluster_id = None
        if label != -1:
            cluster_id = label_to_cluster[label].id

        assignment = ClusterAssignment(
            run_id=run.id,
            feedback_item_id=item.id,
            cluster_id=cluster_id,
            x=float(x),
            y=float(y),
        )
        db.add(assignment)

    db.commit()
    return run
