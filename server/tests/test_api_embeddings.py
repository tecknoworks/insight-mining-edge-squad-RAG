"""Integration tests for the embedding job API: start -> status round-trip.

``get_embedding_client`` is dependency-overridden with a stub — no real
``sentence-transformers`` model load, no network call. Since FastAPI's
``TestClient`` runs ``BackgroundTasks`` synchronously before returning the
response, the job has already finished by the time ``client.post(...)``
returns.
"""

import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.embeddings.client import get_embedding_client
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
DIMENSION = 4


class StubEmbeddingClient:
    """A fake ``EmbeddingClient`` returning fixed-length vectors — no model load."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_documents(
        self, texts: list[str], *, ids: Sequence[str] | None = None
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(text))] * DIMENSION for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


@pytest.fixture
def stub_embedding_client() -> StubEmbeddingClient:
    return StubEmbeddingClient()


@pytest.fixture
def client(
    stub_embedding_client: StubEmbeddingClient, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override_get_db() -> Iterator[Session]:
        session = testing_session_local()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("app.embeddings.service.SessionLocal", testing_session_local)
    monkeypatch.setattr(get_settings(), "embedding_dimension", DIMENSION)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_embedding_client] = lambda: stub_embedding_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _upload(client: TestClient, filename: str) -> str:
    with (FIXTURES / filename).open("rb") as f:
        response = client.post("/ingestion/uploads", files={"file": (filename, f, "text/csv")})
    assert response.status_code == 201
    dataset_id = response.json()["dataset_id"]
    assert dataset_id is not None
    return str(dataset_id)


def test_embed_full_round_trip(
    client: TestClient, stub_embedding_client: StubEmbeddingClient
) -> None:
    dataset_id = _upload(client, "happy_path.csv")

    start_response = client.post(f"/ingestion/datasets/{dataset_id}/embed")
    assert start_response.status_code == 202
    started = start_response.json()
    assert started["items_total"] == 3

    status_response = client.get(f"/ingestion/datasets/{dataset_id}/embed")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["state"] == "completed"
    assert status["items_embedded"] == 3
    assert status["items_failed"] == 0
    assert status["dimension"] == DIMENSION

    detail = client.get(f"/ingestion/datasets/{dataset_id}").json()
    assert detail["status"] == "embedded"


def test_reembed_fully_embedded_dataset_is_a_noop(
    client: TestClient, stub_embedding_client: StubEmbeddingClient
) -> None:
    dataset_id = _upload(client, "happy_path.csv")
    client.post(f"/ingestion/datasets/{dataset_id}/embed")
    stub_embedding_client.calls.clear()

    second_response = client.post(f"/ingestion/datasets/{dataset_id}/embed")
    assert second_response.status_code == 202
    body = second_response.json()
    assert body["items_total"] == 0
    assert body["items_embedded"] == 0
    assert body["state"] == "completed"
    assert stub_embedding_client.calls == []


def test_embed_unknown_dataset_returns_404(client: TestClient) -> None:
    response = client.post(f"/ingestion/datasets/{uuid.uuid4()}/embed")
    assert response.status_code == 404


def test_embed_status_before_any_post_returns_404(client: TestClient) -> None:
    dataset_id = _upload(client, "happy_path.csv")
    response = client.get(f"/ingestion/datasets/{dataset_id}/embed")
    assert response.status_code == 404


def test_double_post_while_running_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_id = _upload(client, "happy_path.csv")

    # Simulate an in-flight job by marking it running before the second POST,
    # bypassing BackgroundTasks' synchronous-in-tests completion.
    import app.api.ingestion as ingestion_routes
    from app.embeddings.service import start_or_resume_job
    from app.models.db import EmbeddingJob
    from app.models.schemas import EmbeddingJobState

    def _start_and_leave_running(db: Session, dataset_id: uuid.UUID) -> EmbeddingJob:
        job = start_or_resume_job(db, dataset_id)
        job.state = EmbeddingJobState.RUNNING
        db.commit()
        return job

    monkeypatch.setattr(ingestion_routes, "start_or_resume_job", _start_and_leave_running)
    monkeypatch.setattr(ingestion_routes, "run_job", lambda *_args, **_kwargs: None)

    first = client.post(f"/ingestion/datasets/{dataset_id}/embed")
    assert first.status_code == 202

    second = client.post(f"/ingestion/datasets/{dataset_id}/embed")
    assert second.status_code == 409
