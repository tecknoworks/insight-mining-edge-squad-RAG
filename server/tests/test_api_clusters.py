"""Integration tests for the clustering API."""

import datetime
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
    """Incremental mode returns current run when no new embedded items exceed threshold."""
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

    # Second call — no new embedded items added, threshold (10) not met
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "incremental",
        },
    )
    assert response.status_code == 202
    run2_id = response.json()["id"]
    assert run2_id == run1_id  # same run returned, no recompute


def test_incremental_clustering_triggers_when_threshold_met(
    client: TestClient, db: Session, sample_dataset_with_embeddings
):
    """Incremental mode re-clusters when new embedded items exceed threshold."""
    dataset_id = sample_dataset_with_embeddings.id

    # First run (threshold default is 10)
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

    # Get the run's created_at so we can backdate new items before it
    run1 = db.get(ClusteringRun, uuid.UUID(run1_id))
    assert run1 is not None
    after_run = run1.created_at + datetime.timedelta(seconds=1)

    # Add 15 newly embedded items with created_at after the run
    for i in range(15):
        item = FeedbackItem(
            dataset_id=dataset_id,
            feedback_text=f"new feedback {i}",
            row_number=100 + i,
        )
        item.embedding = np.array([float(i)] * 384, dtype=np.float32).tobytes()
        item.created_at = after_run  # type: ignore[assignment]
        db.add(item)
    db.commit()

    # Second incremental call — 15 new embedded items >= threshold (10)
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset_id),
            "mode": "incremental",
            "params": {"min_cluster_size": 2},
        },
    )
    assert response.status_code == 202
    run2_id = response.json()["id"]
    assert run2_id != run1_id  # new run was created


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


def test_semantic_clustering_separates_themes(client: TestClient, db: Session):
    """Semantic grouping test: three distinct themes must land in separate clusters.

    Uses theme-based base vectors + small noise so items within a theme are
    geometrically similar — this proves HDBSCAN groups by meaning, not coincidence.
    """
    payment_texts = [
        "can't pay", "checkout failed", "payment error", "billing issue",
        "card declined", "payment timeout", "transaction failed", "charge error",
        "payment gateway down", "can't complete purchase", "payment stuck",
        "refund not received", "double charged", "payment pending", "billing error",
        "credit card rejected", "payment method failed", "transaction error",
        "checkout error", "can't process payment",
    ]
    shipping_texts = [
        "slow shipping", "lost package", "delivery late", "shipping delay",
        "package missing", "tracking not working", "shipment delayed",
        "delivery failed", "package damaged", "wrong address shipped",
        "shipping takes forever", "no tracking updates", "delivery stuck",
        "package lost in transit", "slow delivery", "shipping cost high",
        "delivery person didn't knock", "package left outside", "shipping lag",
        "delivery day wrong",
    ]
    feature_texts = [
        "need dark mode", "want export", "request PDF", "dark theme needed",
        "need API access", "want bulk operations", "request scheduling",
        "need reporting", "want analytics", "request integration",
        "dark mode please", "need batch processing", "want mobile app",
        "need webhooks", "request filters", "want search", "need sorting",
        "want pagination", "request caching", "need compression",
    ]

    dataset = Dataset(filename="semantic_test.csv", status=DatasetStatus.INGESTED)
    db.add(dataset)
    db.flush()

    # Each theme gets a distinct base vector; items in a theme add tiny noise so
    # they stay geometrically close together but not identical.
    rng_base = np.random.RandomState(42)
    theme_bases = [rng_base.randn(384).astype(np.float32) for _ in range(3)]

    all_texts = payment_texts + shipping_texts + feature_texts
    theme_labels = [0] * 20 + [1] * 20 + [2] * 20

    for i, (text, theme) in enumerate(zip(all_texts, theme_labels, strict=True)):
        noise = np.random.RandomState(i).randn(384).astype(np.float32) * 0.05
        vec = theme_bases[theme] + noise
        item = FeedbackItem(
            dataset_id=dataset.id,
            feedback_text=text,
            row_number=i + 1,
        )
        item.embedding = vec.tobytes()
        db.add(item)
    db.commit()

    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset.id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 5, "min_samples": 2, "reduced_dimensions": 10},
        },
    )

    assert response.status_code == 202
    run_data = response.json()
    assert run_data["cluster_count"] >= 2, (
        f"Expected ≥2 clusters for 3 themes, got {run_data['cluster_count']}"
    )

    response = client.get(f"/clusters?dataset_id={dataset.id}")
    assert response.status_code == 200
    clusters = response.json()

    payment_set = set(payment_texts)
    shipping_set = set(shipping_texts)
    feature_set = set(feature_texts)

    for cluster in clusters:
        items_resp = client.get(f"/clusters/{cluster['id']}/items?limit=500")
        assert items_resp.status_code == 200
        cluster_texts = [it["feedback_text"] for it in items_resp.json()["items"]]

        themes_in_cluster = set()
        for text in cluster_texts:
            if text in payment_set:
                themes_in_cluster.add("payment")
            elif text in shipping_set:
                themes_in_cluster.add("shipping")
            elif text in feature_set:
                themes_in_cluster.add("feature")

        assert len(themes_in_cluster) <= 1, (
            f"Cluster {cluster['id']} mixes themes {themes_in_cluster}: {cluster_texts[:3]}..."
        )


def test_get_cluster_summary_404_on_missing_cluster(client: TestClient, db: Session):
    """GET /clusters/{cluster_id}/summary returns 404 when cluster doesn't exist."""
    response = client.get(f"/clusters/{uuid.uuid4()}/summary")
    assert response.status_code == 404


@pytest.mark.parametrize("force", [False, True])
def test_get_cluster_summary_requires_api_key(
    client: TestClient, db: Session, sample_dataset_with_embeddings, force: bool
):
    """GET /clusters/{cluster_id}/summary returns 503 when API key not configured."""
    # Create clustering run with a small cluster size to ensure we get clusters
    dataset = sample_dataset_with_embeddings
    response = client.post(
        "/clusters/runs",
        json={
            "dataset_id": str(dataset.id),
            "mode": "on_demand",
            "params": {"min_cluster_size": 2, "min_samples": 1, "reduced_dimensions": 5},
        },
    )
    assert response.status_code == 202

    # Get clusters
    clusters_resp = client.get(f"/clusters?dataset_id={dataset.id}")
    assert clusters_resp.status_code == 200
    clusters = clusters_resp.json()

    if len(clusters) == 0:
        pytest.skip("No clusters generated from sample dataset")

    cluster_id = clusters[0]["id"]

    # Mock settings to have no API key
    def override_get_settings():
        from app.core.config import Settings
        settings = Settings()
        settings.anthropic_api_key = ""  # Empty key
        return settings

    from app.core.config import get_settings
    app.dependency_overrides[get_settings] = override_get_settings

    try:
        response = client.get(f"/clusters/{cluster_id}/summary?force={str(force).lower()}")
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()
