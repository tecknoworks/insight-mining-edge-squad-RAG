"""Integration tests for the clustering API."""

import uuid
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models.db import ClusterAssignment, ClusteringRun, Dataset, FeedbackItem
from app.models.schemas import DatasetStatus

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(db: Session):
    """FastAPI test client with in-memory database."""

    def override_get_db():
        yield db

    from app.core.db import get_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_post_clusters_runs_creates_run_and_assignments(
    client: TestClient, db: Session, sample_dataset_with_embeddings
):
    """POST /clusters/runs creates a clustering run and assignments."""
    dataset_id = sample_dataset_with_embeddings.id

    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2, "min_samples": 1, "reduced_dimensions": 5},
        },
    )

    assert response.status_code == 202
    run_data = response.json()
    assert run_data["dataset_id"] == str(dataset_id)
    assert run_data["is_current"] is True

    # Verify run in database
    run = db.get(ClusteringRun, uuid.UUID(run_data["id"]))
    assert run is not None
    assert run.is_current is True

    # Verify assignments exist
    assignments = db.execute(
        select(ClusterAssignment).where(ClusterAssignment.run_id == run.id)
    ).scalars().all()
    assert len(assignments) == 3  # happy_path.csv has 3 items


def test_post_clusters_runs_404_on_unknown_dataset(client: TestClient, db: Session):
    """POST /clusters/runs returns 404 when dataset doesn't exist."""
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(uuid.uuid4()),
            "mode": "on_demand",
        },
    )

    assert response.status_code == 404


def test_post_clusters_runs_409_on_no_embeddings(client: TestClient, db: Session, sample_dataset):
    """POST /clusters/runs returns 409 when dataset has no embeddings."""
    dataset_id = sample_dataset.id

    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
        },
    )

    assert response.status_code == 409


def test_get_clusters_runs_by_id(client: TestClient, db: Session, sample_dataset_with_embeddings):
    """GET /clusters/runs/{run_id} returns the clustering run."""
    dataset_id = sample_dataset_with_embeddings.id

    # Create a run first
    response = client.post(
        "/clusters/runs",
        json={"dataset_id": str(dataset_id), "mode": "on_demand"},
    )
    run_id = response.json()["id"]

    # Fetch the run
    response = client.get(f"/clusters/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == run_id


def test_list_clusters(client: TestClient, db: Session, sample_dataset_with_embeddings):
    """GET /clusters lists clusters from the current run."""
    dataset_id = sample_dataset_with_embeddings.id

    # Create a run
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2},
        },
    )
    assert response.status_code == 202

    # List clusters
    response = client.get(f"/clusters?dataset_id={dataset_id}")
    assert response.status_code == 200
    clusters = response.json()
    assert isinstance(clusters, list)
    # May have 0+ clusters depending on clustering output
    for cluster in clusters:
        assert "item_count" in cluster


def test_list_clusters_404_no_run(client: TestClient, db: Session, sample_dataset):
    """GET /clusters returns 404 when no run exists."""
    response = client.get(f"/clusters?dataset_id={sample_dataset.id}")
    assert response.status_code == 404


def test_get_cluster_map(client: TestClient, db: Session, sample_dataset_with_embeddings):
    """GET /clusters/map returns points + cluster metadata."""
    dataset_id = sample_dataset_with_embeddings.id

    # Create a run
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2},
        },
    )
    assert response.status_code == 202

    # Fetch the map
    response = client.get(f"/clusters/map?dataset_id={dataset_id}")
    assert response.status_code == 200
    data = response.json()
    assert "points" in data
    assert "clusters" in data
    assert len(data["points"]) == 3  # happy_path.csv has 3 items
    # Every point should have x, y
    for point in data["points"]:
        assert "x" in point
        assert "y" in point
        assert isinstance(point["x"], float)
        assert isinstance(point["y"], float)


def test_incremental_clustering_skips_recompute(
    client: TestClient, db: Session, sample_dataset_with_embeddings
):
    """Incremental mode returns current run if threshold not met."""
    dataset_id = sample_dataset_with_embeddings.id

    # First run
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "incremental",
            "params": {"min_cluster_size": 2},
        },
    )
    assert response.status_code == 202
    run1_id = response.json()["id"]

    # Second call with incremental mode, no new embeddings
    # Should return the same run without recomputing
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "incremental",
        },
    )
    assert response.status_code == 202
    run2_id = response.json()["id"]
    # Should be the same run
    assert run2_id == run1_id


def test_on_demand_clustering_always_recomputes(
    client: TestClient, db: Session, sample_dataset_with_embeddings
):
    """On-demand mode always creates a new run."""
    dataset_id = sample_dataset_with_embeddings.id

    # First run
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2},
        },
    )
    assert response.status_code == 202
    run1_id = response.json()["id"]

    # Second run with on_demand mode
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2},
        },
    )
    assert response.status_code == 202
    run2_id = response.json()["id"]
    # Should be different runs
    assert run2_id != run1_id

    # Both runs should exist
    run1 = db.get(ClusteringRun, uuid.UUID(run1_id))
    run2 = db.get(ClusteringRun, uuid.UUID(run2_id))
    assert run1 is not None
    assert run2 is not None
    # Only the latest run should be current
    assert run1.is_current is False
    assert run2.is_current is True


def test_second_run_flips_is_current(
    client: TestClient, db: Session, sample_dataset_with_embeddings
):
    """A second run marks the previous run as not current."""
    dataset_id = sample_dataset_with_embeddings.id

    # First run
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2},
        },
    )
    run1_id = uuid.UUID(response.json()["id"])

    # Second run
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2},
        },
    )
    run2_id = uuid.UUID(response.json()["id"])

    # Verify only run2 is current
    run1 = db.get(ClusteringRun, run1_id)
    run2 = db.get(ClusteringRun, run2_id)
    assert run1.is_current is False
    assert run2.is_current is True


def test_degenerate_input_too_few_items(client: TestClient, db: Session):
    """Dataset with fewer items than min_cluster_size returns a valid run with no clusters."""

    # Create a dataset with just 1 item
    dataset = Dataset(filename="tiny.csv", status=DatasetStatus.INGESTED)
    db.add(dataset)
    db.flush()

    item = FeedbackItem(
        dataset_id=dataset.id,
        feedback_text="hello",
        row_number=1,
    )
    # Add an embedding
    item.embedding = np.array([1.0] * 384, dtype=np.float32).tobytes()
    db.add(item)
    db.commit()

    # Verify item exists with embedding
    items = db.execute(
        select(FeedbackItem).where(FeedbackItem.dataset_id == dataset.id)
    ).scalars().all()
    assert len(items) == 1
    assert items[0].embedding is not None

    # Clustering with min_cluster_size=10 should succeed with all items as noise
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset.id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 10},
        },
    )

    assert response.status_code == 202, f"Got {response.status_code}: {response.json()}"
    run_data = response.json()
    assert run_data["cluster_count"] == 0
    assert run_data["noise_count"] == 1


def test_list_cluster_items(client: TestClient, db: Session, sample_dataset_with_embeddings):
    """GET /clusters/{cluster_id}/items paginates items in a cluster."""
    dataset_id = sample_dataset_with_embeddings.id

    # Create a run
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2},
        },
    )

    # Get the first cluster
    response = client.get(f"/clusters?dataset_id={dataset_id}")
    clusters = response.json()
    if clusters:
        cluster_id = clusters[0]["id"]

        # List items in the cluster
        response = client.get(f"/clusters/{cluster_id}/items?limit=10&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        # Items should have the required fields
        for item in data["items"]:
            assert "feedback_text" in item
            assert "source" in item
            assert "submitted_at" in item
            assert "customer_id" in item
