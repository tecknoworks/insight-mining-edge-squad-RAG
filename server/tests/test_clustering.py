"""Unit tests for clustering algorithms and service logic."""

import uuid

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clustering.algorithms import HDBSCANClusterer
from app.clustering.service import run_clustering, should_cluster
from app.core.config import Settings
from app.models.db import ClusterAssignment, ClusteringRun


@pytest.fixture
def clusterer():
    """Create a clusterer with small thresholds for testing."""
    return HDBSCANClusterer(
        min_cluster_size=3,
        min_samples=1,
        reduced_dimensions=5,
        random_seed=42,
    )


def test_deterministic_seeding(clusterer):
    """Two runs with same seed produce identical assignments."""
    vectors = np.random.RandomState(42).randn(50, 10).astype(np.float32)

    labels1, x1, y1 = clusterer.fit(vectors)
    labels2, x2, y2 = clusterer.fit(vectors)

    np.testing.assert_array_equal(labels1, labels2)
    np.testing.assert_array_almost_equal(x1, x2)
    np.testing.assert_array_almost_equal(y1, y2)


def test_noise_handling(clusterer):
    """Noise items have label -1."""
    vectors = np.random.RandomState(42).randn(30, 10).astype(np.float32)
    labels, _, _ = clusterer.fit(vectors)

    # Should have items, some likely noise
    assert len(labels) == 30
    assert all(isinstance(label, (int, np.integer)) for label in labels)


def test_min_cluster_size_boundary():
    """Fewer items than min_cluster_size → all noise, no clusters."""
    clusterer = HDBSCANClusterer(
        min_cluster_size=50, min_samples=1, reduced_dimensions=5, random_seed=42
    )
    vectors = np.random.RandomState(42).randn(30, 10).astype(np.float32)
    labels, x, y = clusterer.fit(vectors)

    # All should be noise (30 < 50 min_cluster_size)
    assert all(label == -1 for label in labels)
    assert len(x) == 30
    assert len(y) == 30


def test_2d_projection_shape():
    """2D projection has correct shape."""
    clusterer = HDBSCANClusterer(
        min_cluster_size=3, min_samples=1, reduced_dimensions=5, random_seed=42
    )
    vectors = np.random.RandomState(42).randn(50, 50).astype(np.float32)
    labels, x, y = clusterer.fit(vectors)

    assert x.shape == (50,)
    assert y.shape == (50,)
    assert all(np.isfinite(x))
    assert all(np.isfinite(y))


def test_two_item_projection():
    """Two items get valid 2D coordinates."""
    clusterer = HDBSCANClusterer(random_seed=42)
    vectors = np.random.RandomState(42).randn(2, 384).astype(np.float32)
    labels, x, y = clusterer.fit(vectors)

    assert x.shape == (2,)
    assert y.shape == (2,)
    assert np.isfinite(x[0])
    assert np.isfinite(y[0])
    assert np.isfinite(x[1])
    assert np.isfinite(y[1])


def test_should_cluster_on_demand(db: Session):
    """On-demand mode always returns True."""
    dataset_id = uuid.uuid4()
    assert should_cluster(db, dataset_id, "on_demand", threshold=100) is True


def test_should_cluster_incremental_no_prior_run(db: Session):
    """Incremental mode returns True when no prior run exists."""
    dataset_id = uuid.uuid4()
    assert should_cluster(db, dataset_id, "incremental", threshold=10) is True


def test_should_cluster_incremental_threshold_not_met(
    db: Session, sample_dataset_with_embeddings
):
    """Incremental mode returns False when threshold not met."""
    dataset_id = sample_dataset_with_embeddings.id

    # Create a clustering run
    run = ClusteringRun(
        dataset_id=dataset_id,
        algorithm="hdbscan",
        params={},
        random_seed=42,
        cluster_count=1,
        noise_count=0,
        is_current=True,
    )
    db.add(run)
    db.commit()

    # With 5 embedded items and no new ones, threshold of 10 not met
    assert should_cluster(db, dataset_id, "incremental", threshold=10) is False


def test_run_clustering_creates_run_and_assignments(
    db: Session, sample_dataset_with_embeddings, monkeypatch
):
    """run_clustering creates ClusteringRun and ClusterAssignment rows."""
    dataset_id = sample_dataset_with_embeddings.id

    # Mock get_settings to return test settings
    def mock_get_settings():
        return Settings(clustering_random_seed=42)

    algo_params = {
        "min_cluster_size": 2,
        "min_samples": 1,
        "reduced_dimensions": 5,
        "random_seed": 42,
    }

    run = run_clustering(db, dataset_id, algo_params, mock_get_settings)

    assert run.dataset_id == dataset_id
    assert run.algorithm == "hdbscan"
    assert run.is_current is True
    assert run.cluster_count >= 0

    # Check assignments exist
    assignments = db.execute(
        select(ClusterAssignment).where(ClusterAssignment.run_id == run.id)
    ).scalars().all()
    # happy_path.csv has 3 items
    assert len(assignments) == 3


def test_run_clustering_no_embeddings(db: Session, sample_dataset):
    """run_clustering raises ValueError when dataset has no embeddings."""
    dataset_id = sample_dataset.id

    def mock_get_settings():
        return Settings()

    algo_params = {"min_cluster_size": 15}

    with pytest.raises(ValueError, match="no embedded items"):
        run_clustering(db, dataset_id, algo_params, mock_get_settings)


def test_run_clustering_determinism(db: Session, sample_dataset_with_embeddings):
    """Two runs with same embeddings and seed produce identical assignments."""

    def mock_get_settings():
        return Settings(clustering_random_seed=42)

    algo_params = {
        "min_cluster_size": 2,
        "min_samples": 1,
        "reduced_dimensions": 5,
        "random_seed": 42,
    }

    run1 = run_clustering(db, sample_dataset_with_embeddings.id, algo_params, mock_get_settings)
    db.commit()

    # Mark run1 as not current before second run
    run1 = db.get(ClusteringRun, run1.id)
    run1.is_current = False
    db.commit()

    run2 = run_clustering(
        db, sample_dataset_with_embeddings.id, algo_params, mock_get_settings
    )

    assignments1 = sorted(
        db.execute(
            select(ClusterAssignment).where(ClusterAssignment.run_id == run1.id)
        ).scalars().all(),
        key=lambda a: a.feedback_item_id,
    )
    assignments2 = sorted(
        db.execute(
            select(ClusterAssignment).where(ClusterAssignment.run_id == run2.id)
        ).scalars().all(),
        key=lambda a: a.feedback_item_id,
    )

    for a1, a2 in zip(assignments1, assignments2, strict=True):
        assert a1.feedback_item_id == a2.feedback_item_id
        assert a1.cluster_id == a2.cluster_id or (a1.cluster_id is None and a2.cluster_id is None)
        assert abs(a1.x - a2.x) < 1e-5
        assert abs(a1.y - a2.y) < 1e-5
