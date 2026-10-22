"""Integration tests for the chat API surface.

``TestClient`` buffers a streaming response, so ordering is asserted on the
order of frames *in the byte stream* — never on wall-clock interleaving, which
would be testing the test client rather than the endpoint.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.chat import get_anthropic_client
from app.core.config import Settings, get_settings
from app.core.db import Base, get_db
from app.embeddings.client import get_embedding_client
from app.main import app
from app.models.db import ChatMessage, Conversation, Dataset, FeedbackItem
from app.models.schemas import ChatRole
from tests.test_insights_chat import FakeAnthropic, StubEmbeddingClient

DIM = 4

# Two orthogonal directions so "in corpus" and "out of corpus" are unambiguous.
CHECKOUT_VECTOR = (1.0, 0.0, 0.0, 0.0)
SHIPPING_VECTOR = (0.0, 1.0, 0.0, 0.0)


def _parse_sse(body: str) -> list[tuple[str | None, object]]:
    """Parse an SSE body into (event, data) frames, skipping `:` keepalive comments."""
    frames: list[tuple[str | None, object]] = []
    for block in body.split("\n\n"):
        event: str | None = None
        data_lines: list[str] = []
        for line in block.strip("\n").split("\n"):
            if not line or line.startswith(":"):
                continue  # blank or keepalive comment
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if event is None and not data_lines:
            continue
        payload = json.loads("\n".join(data_lines)) if data_lines else None
        frames.append((event, payload))
    return frames


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def fake_anthropic() -> FakeAnthropic:
    return FakeAnthropic(["Customers say checkout ", "fails at payment [1]."])


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key",
        embedding_dimension=DIM,
        chat_top_k=5,
        chat_max_distance=0.5,
        chat_max_tokens=2048,
        chat_max_history_tokens=1000,
    )


@pytest.fixture
def embedder() -> StubEmbeddingClient:
    return StubEmbeddingClient(list(CHECKOUT_VECTOR))


@pytest.fixture
def client(db, session_factory, fake_anthropic, test_settings, embedder, monkeypatch):
    """Test client with every external collaborator injected.

    ``stream_turn`` opens its own session via ``SessionLocal``, so that is
    pointed at the test database too — otherwise the assistant message would be
    written to the real SQLite file.
    """
    monkeypatch.setattr("app.insights.chat.SessionLocal", session_factory, raising=False)
    monkeypatch.setattr("app.api.chat.SessionLocal", session_factory)

    def override_get_db() -> Iterator[Session]:
        yield db

    overrides = {
        get_db: override_get_db,
        get_settings: lambda: test_settings,
        get_embedding_client: lambda: embedder,
        get_anthropic_client: lambda: fake_anthropic,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app)
    finally:
        # Pop only what this fixture set — clear() would wipe overrides other
        # fixtures installed.
        for key in overrides:
            app.dependency_overrides.pop(key, None)


def _seed_two_topic_corpus(db: Session) -> Dataset:
    """A corpus about checkout and about shipping, on orthogonal vectors."""
    dataset = Dataset(filename="feedback.csv")
    db.add(dataset)
    db.flush()
    rows = [
        ("checkout failed with an error at payment", CHECKOUT_VECTOR, "support ticket"),
        ("could not pay, card was declined", CHECKOUT_VECTOR, "support ticket"),
        ("shipping took three weeks to arrive", SHIPPING_VECTOR, "app review"),
        ("delivery was late again", SHIPPING_VECTOR, "app review"),
    ]
    for index, (text, vector, source) in enumerate(rows):
        db.add(
            FeedbackItem(
                dataset_id=dataset.id,
                feedback_text=text,
                source=source,
                submitted_at=datetime(2026, 3, index + 1, 12, 0),
                row_number=index,
                embedding=np.asarray(vector, dtype=np.float32).tobytes(),
            )
        )
    db.commit()
    return dataset


def test_streams_tokens_then_citations_then_done(client, db, fake_anthropic):
    """AC 1: SSE frames arrive in the required order and terminate with done."""
    dataset = _seed_two_topic_corpus(db)

    response = client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "what about checkout?"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    frames = _parse_sse(response.text)
    assert [event for event, _ in frames] == ["token", "token", "citations", "done"]

    _, done = frames[-1]
    assert uuid.UUID(done["conversation_id"])
    assert uuid.UUID(done["message_id"])


def test_answer_cites_items_from_the_requested_dataset(client, db):
    """AC 6: every cited id exists in the dataset that was asked about."""
    dataset = _seed_two_topic_corpus(db)

    response = client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "what about checkout?"},
    )

    _, citations = next(f for f in _parse_sse(response.text) if f[0] == "citations")
    assert citations["items"]

    dataset_item_ids = {
        str(row_id)
        for (row_id,) in db.query(FeedbackItem.id).filter_by(dataset_id=dataset.id).all()
    }
    for item in citations["items"]:
        assert item["feedback_item_id"] in dataset_item_ids
        assert len(item["excerpt"]) <= 201


def test_out_of_corpus_question_declines_with_zero_claude_calls(
    client, db, fake_anthropic, embedder
):
    """AC 5 + AC 7: nothing relevant retrieved => grounded refusal, no Claude call."""
    dataset = _seed_two_topic_corpus(db)
    # Query direction orthogonal to every stored vector => distance 1.0 > 0.5.
    embedder._vector = [0.0, 0.0, 1.0, 0.0]

    response = client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "what about pricing?"},
    )

    frames = _parse_sse(response.text)
    assert [event for event, _ in frames] == ["token", "citations", "done"]
    assert "don't have feedback about that" in frames[0][1]["text"]
    assert frames[1][1]["items"] == []
    assert fake_anthropic.call_count == 0


def test_uses_the_query_embedding_path(client, db, embedder):
    """AC 2: the question is embedded via embed_query, not embed_documents."""
    dataset = _seed_two_topic_corpus(db)

    client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "why does checkout fail?"},
    )

    assert embedder.query_calls == ["why does checkout fail?"]
    assert embedder.document_calls == []


def test_source_filter_narrows_retrieval(client, db, fake_anthropic):
    """AC 4 end-to-end: a source filter reaches the SQL candidate set."""
    dataset = _seed_two_topic_corpus(db)

    client.post(
        "/chat/messages",
        json={
            "dataset_id": str(dataset.id),
            "message": "what about checkout?",
            "filters": {"source": ["app review"]},
        },
    )

    # Only the two 'app review' rows could be candidates, and they are
    # orthogonal to the checkout query, so nothing clears the floor.
    assert fake_anthropic.call_count == 0


def test_sends_configured_model_and_no_sampling_parameters(client, db, fake_anthropic):
    """AC 8 + AC 9 asserted on the real request kwargs."""
    dataset = _seed_two_topic_corpus(db)

    client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "what about checkout?"},
    )

    kwargs = fake_anthropic.messages.stream_calls[0]
    assert kwargs["model"] == "claude-haiku-4-5"
    assert not {"temperature", "top_p", "top_k"} & kwargs.keys()


def test_mid_stream_failure_emits_error_without_done(client, db, session_factory):
    """AC 11: error frame, stream closes, no done and no citations."""
    dataset = _seed_two_topic_corpus(db)
    app.dependency_overrides[get_anthropic_client] = lambda: FakeAnthropic(
        ["partial ", "boom"], fail_at=1
    )

    response = client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "what about checkout?"},
    )

    assert response.status_code == 200
    events = [event for event, _ in _parse_sse(response.text)]
    assert events == ["token", "error"]
    assert "done" not in events
    assert "citations" not in events


def test_unknown_dataset_returns_404(client):
    response = client.post(
        "/chat/messages", json={"dataset_id": str(uuid.uuid4()), "message": "hi"}
    )

    assert response.status_code == 404


def test_unknown_conversation_returns_404(client, db):
    dataset = _seed_two_topic_corpus(db)

    response = client.post(
        "/chat/messages",
        json={
            "dataset_id": str(dataset.id),
            "message": "hi",
            "conversation_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 404


def test_empty_message_is_rejected(client, db):
    dataset = _seed_two_topic_corpus(db)

    response = client.post(
        "/chat/messages", json={"dataset_id": str(dataset.id), "message": ""}
    )

    assert response.status_code == 422


def test_missing_api_key_returns_503_before_the_stream_starts(client, db):
    """A JSON error is only possible because this is decided in a dependency."""
    dataset = _seed_two_topic_corpus(db)
    app.dependency_overrides[get_anthropic_client] = lambda: None

    response = client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "what about checkout?"},
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_conversation_replays_messages_in_sequence_order(client, db):
    """AC 10: two turns replay in order, which created_at alone would not guarantee."""
    dataset = _seed_two_topic_corpus(db)

    first = client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "first question"},
    )
    conversation_id = next(f for f in _parse_sse(first.text) if f[0] == "done")[1][
        "conversation_id"
    ]

    client.post(
        "/chat/messages",
        json={
            "dataset_id": str(dataset.id),
            "message": "second question",
            "conversation_id": conversation_id,
        },
    )

    response = client.get(f"/chat/conversations/{conversation_id}")

    assert response.status_code == 200
    body = response.json()
    assert [m["sequence"] for m in body["messages"]] == [0, 1, 2, 3]
    assert [m["role"] for m in body["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert body["messages"][0]["content"] == "first question"
    assert body["messages"][2]["content"] == "second question"


def test_second_turn_replays_history_to_claude(client, db, fake_anthropic):
    dataset = _seed_two_topic_corpus(db)

    first = client.post(
        "/chat/messages", json={"dataset_id": str(dataset.id), "message": "first question"}
    )
    conversation_id = next(f for f in _parse_sse(first.text) if f[0] == "done")[1][
        "conversation_id"
    ]

    client.post(
        "/chat/messages",
        json={
            "dataset_id": str(dataset.id),
            "message": "follow up",
            "conversation_id": conversation_id,
        },
    )

    second_call = fake_anthropic.messages.stream_calls[1]
    assert [m["content"] for m in second_call["messages"][:1]] == ["first question"]


def test_unknown_conversation_get_returns_404(client):
    assert client.get(f"/chat/conversations/{uuid.uuid4()}").status_code == 404


def test_assistant_turn_is_persisted_with_its_citations(client, db, session_factory):
    dataset = _seed_two_topic_corpus(db)

    response = client.post(
        "/chat/messages",
        json={"dataset_id": str(dataset.id), "message": "what about checkout?"},
    )
    done = next(f for f in _parse_sse(response.text) if f[0] == "done")[1]

    session = session_factory()
    try:
        stored = session.get(ChatMessage, uuid.UUID(done["message_id"]))
        assert stored is not None
        assert stored.role == ChatRole.ASSISTANT
        assert stored.citations
        conversation = session.get(Conversation, uuid.UUID(done["conversation_id"]))
        assert conversation is not None
        assert conversation.dataset_id == dataset.id
    finally:
        session.close()
