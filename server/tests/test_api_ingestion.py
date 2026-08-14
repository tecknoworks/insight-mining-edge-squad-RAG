"""Integration tests for the ingestion API: upload -> list -> detail."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override_get_db() -> Iterator[Session]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _upload(client: TestClient, filename: str, path: Path) -> httpx.Response:
    with path.open("rb") as f:
        response: httpx.Response = client.post(
            "/ingestion/uploads", files={"file": (filename, f, "text/csv")}
        )
        return response


def test_full_upload_list_detail_round_trip(client: TestClient) -> None:
    response = _upload(client, "happy_path.csv", FIXTURES / "happy_path.csv")
    assert response.status_code == 201
    report = response.json()
    assert report["rows_total"] == 3
    assert report["rows_accepted"] == 3
    assert report["rows_rejected"] == 0
    dataset_id = report["dataset_id"]
    assert dataset_id is not None

    list_response = client.get("/ingestion/datasets")
    assert list_response.status_code == 200
    datasets = list_response.json()
    assert len(datasets) == 1
    assert datasets[0]["id"] == dataset_id
    assert datasets[0]["row_count_accepted"] == 3

    detail_response = client.get(f"/ingestion/datasets/{dataset_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["filename"] == "happy_path.csv"
    assert len(detail["feedback_items"]) == 3

    first_item = detail["feedback_items"][0]
    assert first_item["feedback_text"] == "Checkout kept failing on the last step"
    assert first_item["source"] == "support ticket"
    assert first_item["customer_id"] == "cust-001"
    assert first_item["submitted_at"] == "2026-03-14T00:00:00"

    third_item = detail["feedback_items"][2]
    assert third_item["submitted_at"] == "2026-03-16T00:00:00"


def test_optional_fields_survive_when_absent(client: TestClient) -> None:
    response = _upload(client, "all_optional_absent.csv", FIXTURES / "all_optional_absent.csv")
    assert response.status_code == 201
    dataset_id = response.json()["dataset_id"]

    detail = client.get(f"/ingestion/datasets/{dataset_id}").json()
    for item in detail["feedback_items"]:
        assert item["source"] is None
        assert item["customer_id"] is None
        assert item["submitted_at"] is None


def test_missing_required_column_returns_400_and_persists_nothing(client: TestClient) -> None:
    response = _upload(
        client, "missing_required_column.csv", FIXTURES / "missing_required_column.csv"
    )
    assert response.status_code == 400

    datasets = client.get("/ingestion/datasets").json()
    assert datasets == []


def test_all_rows_invalid_returns_400_and_persists_nothing(client: TestClient) -> None:
    response = _upload(client, "all_rows_invalid.csv", FIXTURES / "all_rows_invalid.csv")
    assert response.status_code == 400
    body = response.json()
    assert body["rows_accepted"] == 0
    assert body["dataset_id"] is None

    datasets = client.get("/ingestion/datasets").json()
    assert datasets == []


def test_get_dataset_unknown_uuid_returns_404(client: TestClient) -> None:
    response = client.get(f"/ingestion/datasets/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_dataset_malformed_uuid_returns_422(client: TestClient) -> None:
    response = client.get("/ingestion/datasets/not-a-uuid")
    assert response.status_code == 422


def test_list_datasets_newest_first(client: TestClient) -> None:
    _upload(client, "happy_path.csv", FIXTURES / "happy_path.csv")
    _upload(client, "all_optional_absent.csv", FIXTURES / "all_optional_absent.csv")

    datasets = client.get("/ingestion/datasets").json()
    assert [d["filename"] for d in datasets] == ["all_optional_absent.csv", "happy_path.csv"]
