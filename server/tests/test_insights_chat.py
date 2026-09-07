"""Unit tests for chat orchestration: citations, history budget, event ordering.

The Anthropic client is a hand-written fake rather than a ``MagicMock`` — the
streaming call is used as a context manager that exposes ``text_stream`` and
``get_final_message()``, which a bare mock cannot model, and the fake records
the exact kwargs so model/sampling-parameter assertions are runtime facts
rather than greps.
"""

import uuid
from collections.abc import Iterator
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.insights.chat import (
    ConversationNotFoundError,
    DatasetNotFoundError,
    LlmUnavailableError,
    PreparedTurn,
    prepare_turn,
    stream_turn,
    truncate_history,
)
from app.insights.citations import build_citations, parse_cited_indices, truncate_text
from app.insights.prompts import (
    CHAT_SYSTEM_PROMPT,
    NO_RELEVANT_FEEDBACK_ANSWER,
    build_user_message,
    format_context_block,
)
from app.insights.retrieval import RetrievedItem
from app.models.db import ChatMessage, Conversation, Dataset, FeedbackItem
from app.models.schemas import ChatMessageRequest, ChatRole

DIM = 4


# --- fakes ------------------------------------------------------------------


class FakeStream:
    """Stands in for the context manager returned by ``messages.stream``."""

    def __init__(
        self,
        chunks: list[str],
        *,
        fail_at: int | None = None,
        stop_reason: str = "end_turn",
    ) -> None:
        self._chunks = chunks
        self._fail_at = fail_at
        self._stop_reason = stop_reason
        self.closed = False

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.closed = True
        return False

    @property
    def text_stream(self) -> Iterator[str]:
        for index, chunk in enumerate(self._chunks):
            if self._fail_at is not None and index == self._fail_at:
                raise RuntimeError("provider exploded mid-stream")
            yield chunk

    def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=123, output_tokens=45),
            stop_reason=self._stop_reason,
        )


class FakeMessages:
    def __init__(self, stream_factory, token_count: int) -> None:
        self._stream_factory = stream_factory
        self._token_count = token_count
        self.stream_calls: list[dict] = []
        self.count_tokens_calls: list[dict] = []

    def stream(self, **kwargs: object) -> FakeStream:
        self.stream_calls.append(kwargs)
        return self._stream_factory()

    def count_tokens(self, **kwargs: object) -> SimpleNamespace:
        self.count_tokens_calls.append(kwargs)
        count = self._token_count
        if callable(count):
            count = count(kwargs)
        return SimpleNamespace(input_tokens=count)


class FakeAnthropic:
    """Records every call so "made zero Claude calls" is directly assertable."""

    def __init__(self, chunks: list[str] | None = None, *, fail_at=None, token_count=10) -> None:
        self.messages = FakeMessages(
            lambda: FakeStream(chunks or ["answer"], fail_at=fail_at), token_count
        )

    @property
    def call_count(self) -> int:
        return len(self.messages.stream_calls) + len(self.messages.count_tokens_calls)


class StubEmbeddingClient:
    """Records which code path was used — documents vs query (AC 2)."""

    def __init__(self, vector: list[float] | None = None) -> None:
        self._vector = vector or [1.0, 0.0, 0.0, 0.0]
        self.query_calls: list[str] = []
        self.document_calls: list[list[str]] = []

    def embed_documents(self, texts: list[str], *, ids=None) -> list[list[float]]:
        self.document_calls.append(texts)
        return [self._vector for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self._vector


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def session_factory():
    """A sessionmaker over one shared in-memory database.

    ``stream_turn`` opens its own session for the final write, so tests need a
    factory as well as a session — ``StaticPool`` keeps them on the same
    in-memory connection.
    """
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def chat_db(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key",
        embedding_dimension=DIM,
        chat_top_k=5,
        chat_max_distance=0.5,
        chat_max_history_tokens=1000,
        chat_max_tokens=2048,
    )


def _seed_corpus(db: Session, *, texts: list[str], vector=(1.0, 0.0, 0.0, 0.0)) -> Dataset:
    import numpy as np

    dataset = Dataset(filename="corpus.csv")
    db.add(dataset)
    db.flush()
    for index, text in enumerate(texts):
        db.add(
            FeedbackItem(
                dataset_id=dataset.id,
                feedback_text=text,
                row_number=index,
                source="support",
                submitted_at=datetime(2026, 3, 1, 12, 0),
                embedding=np.asarray(vector, dtype=np.float32).tobytes(),
            )
        )
    db.commit()
    return dataset


def _item(text: str, index: int = 0) -> RetrievedItem:
    return RetrievedItem(
        id=uuid.uuid4(),
        feedback_text=text,
        source="support",
        submitted_at=datetime(2026, 3, 1, 12, 0),
        distance=0.1 * index,
    )


# --- citations --------------------------------------------------------------


def test_parse_cited_indices_reads_single_and_grouped_forms():
    assert parse_cited_indices("Checkout fails [1] and [2, 3] confirm it.", 3) == [1, 2, 3]


def test_parse_cited_indices_dedupes_preserving_first_appearance():
    assert parse_cited_indices("[3] then [1] then [3] again", 3) == [3, 1]


def test_parse_cited_indices_drops_out_of_range():
    """The model citing an item it was never shown must not become a citation."""
    assert parse_cited_indices("real [2], invented [9]", 3) == [2]


def test_parse_cited_indices_ignores_prose_references():
    assert parse_cited_indices("as item 3 shows", 5) == []


def test_build_citations_maps_indices_to_items():
    items = [_item("first feedback", 0), _item("second feedback", 1)]

    citations = build_citations("Only [2] matters.", items)

    assert len(citations) == 1
    assert citations[0].feedback_item_id == items[1].id
    assert citations[0].excerpt == "second feedback"
    assert citations[0].source == "support"


def test_build_citations_returns_empty_when_nothing_cited():
    """Never pad with "all retrieved" — the event reports what was used."""
    assert build_citations("No citations here.", [_item("a"), _item("b")]) == []


def test_build_citations_truncates_long_excerpts_on_a_word_boundary():
    long_text = "word " * 100
    citations = build_citations("[1]", [_item(long_text.strip())])

    excerpt = citations[0].excerpt
    assert excerpt.endswith("…")
    assert len(excerpt) <= 201  # 200 + the ellipsis
    assert not excerpt.rstrip("…").endswith("wor")  # cut at a boundary, not mid-word


def test_truncate_text_leaves_short_text_alone():
    assert truncate_text("short", 200) == ("short", False)


def test_truncate_text_hard_cut_by_default():
    """Existing summarizer behaviour: a hard cut, no word-boundary logic."""
    text = "a" * 250
    result, truncated = truncate_text(text, 200)
    assert truncated is True
    assert result == "a" * 200 + "…"


def test_truncate_text_word_boundary_survives_a_single_long_token():
    """A boundary cut must not collapse to just an ellipsis."""
    result, _ = truncate_text("a" * 250, 200, word_boundary=True)
    assert result == "a" * 200 + "…"


# --- prompts ----------------------------------------------------------------


def test_format_context_block_numbers_items_from_one():
    block = format_context_block([_item("first"), _item("second")])

    assert block.startswith("[1] Feedback: first")
    assert "[2] Feedback: second" in block


def test_format_context_block_includes_source_and_date():
    block = format_context_block([_item("text")])

    assert "Source: support" in block
    assert "Date: 2026-03-01T12:00:00" in block


def test_format_context_block_omits_absent_optional_fields():
    bare = RetrievedItem(
        id=uuid.uuid4(), feedback_text="text", source=None, submitted_at=None, distance=0.0
    )
    block = format_context_block([bare])

    assert "Source:" not in block
    assert "Date:" not in block


def test_build_user_message_puts_the_question_after_the_context():
    message = build_user_message("Why?", [_item("because")])

    assert message.index("because") < message.index("Question: Why?")


# --- history truncation -----------------------------------------------------


def _history(pairs: int) -> list[dict]:
    messages: list[dict] = []
    for index in range(pairs):
        messages.append({"role": "user", "content": f"question {index}"})
        messages.append({"role": "assistant", "content": f"answer {index}"})
    return messages


def test_truncate_history_keeps_everything_within_budget():
    client = FakeAnthropic(token_count=10)
    history = _history(2)

    assert truncate_history(history, max_tokens=1000, client=client, model="m") == history


def test_truncate_history_drops_oldest_pairs_first():
    """Over budget on the local estimate, so the oldest turns go first."""
    client = FakeAnthropic(token_count=1)
    history = _history(4)

    kept = truncate_history(history, max_tokens=5, client=client, model="m")

    assert kept[0]["content"] == "question 3"
    assert len(kept) == 2


def test_truncate_history_never_leaves_a_leading_assistant_turn():
    client = FakeAnthropic(token_count=1)

    for pairs in range(1, 5):
        kept = truncate_history(_history(pairs), max_tokens=3, client=client, model="m")
        assert not kept or kept[0]["role"] == "user"


def test_truncate_history_verifies_with_a_single_count_tokens_call():
    """One round-trip, not one per message (contrast summarizer's per-item loop)."""
    client = FakeAnthropic(token_count=10)

    truncate_history(_history(5), max_tokens=1000, client=client, model="m")

    assert len(client.messages.count_tokens_calls) == 1


def test_truncate_history_drops_more_when_the_authoritative_count_is_over():
    """Local estimate says it fits, count_tokens disagrees, so more is dropped."""
    counts = iter([9999, 9999, 5])
    client = FakeAnthropic(token_count=lambda _kwargs: next(counts))

    kept = truncate_history(_history(4), max_tokens=100, client=client, model="m")

    assert len(kept) == 4  # 8 messages minus two dropped pairs
    assert len(client.messages.count_tokens_calls) == 3


# --- prepare_turn -----------------------------------------------------------


def test_prepare_turn_missing_dataset_raises(chat_db, settings):
    with pytest.raises(DatasetNotFoundError):
        prepare_turn(
            chat_db,
            request=ChatMessageRequest(dataset_id=uuid.uuid4(), message="hi"),
            embedding_client=StubEmbeddingClient(),
            settings=settings,
            client=FakeAnthropic(),
        )


def test_prepare_turn_missing_conversation_raises(chat_db, settings):
    dataset = _seed_corpus(chat_db, texts=["checkout failed"])

    with pytest.raises(ConversationNotFoundError):
        prepare_turn(
            chat_db,
            request=ChatMessageRequest(
                dataset_id=dataset.id, message="hi", conversation_id=uuid.uuid4()
            ),
            embedding_client=StubEmbeddingClient(),
            settings=settings,
            client=FakeAnthropic(),
        )


def test_prepare_turn_rejects_a_conversation_from_another_dataset(chat_db, settings):
    """Answering across datasets would mix corpora — refuse, don't re-scope."""
    first = _seed_corpus(chat_db, texts=["checkout failed"])
    second = _seed_corpus(chat_db, texts=["shipping late"])
    conversation = Conversation(dataset_id=second.id)
    chat_db.add(conversation)
    chat_db.commit()

    with pytest.raises(ConversationNotFoundError):
        prepare_turn(
            chat_db,
            request=ChatMessageRequest(
                dataset_id=first.id, message="hi", conversation_id=conversation.id
            ),
            embedding_client=StubEmbeddingClient(),
            settings=settings,
            client=FakeAnthropic(),
        )


def test_prepare_turn_uses_the_query_embedding_path(chat_db, settings):
    """AC 2: the question goes through embed_query, not embed_documents."""
    dataset = _seed_corpus(chat_db, texts=["checkout failed"])
    embedder = StubEmbeddingClient()

    prepare_turn(
        chat_db,
        request=ChatMessageRequest(dataset_id=dataset.id, message="why does checkout fail?"),
        embedding_client=embedder,
        settings=settings,
        client=FakeAnthropic(),
    )

    assert embedder.query_calls == ["why does checkout fail?"]
    assert embedder.document_calls == []


def test_prepare_turn_persists_the_user_message_immediately(chat_db, settings):
    """Committed up front so a mid-stream disconnect still keeps the question."""
    dataset = _seed_corpus(chat_db, texts=["checkout failed"])

    turn = prepare_turn(
        chat_db,
        request=ChatMessageRequest(dataset_id=dataset.id, message="my question"),
        embedding_client=StubEmbeddingClient(),
        settings=settings,
        client=FakeAnthropic(),
    )

    stored = chat_db.query(ChatMessage).filter_by(conversation_id=turn.conversation_id).all()
    assert [(m.role, m.content, m.sequence) for m in stored] == [
        (ChatRole.USER, "my question", 0)
    ]
    assert turn.assistant_sequence == 1


def test_prepare_turn_short_circuits_without_touching_claude(chat_db, settings):
    """AC 5: nothing within max_distance means no Claude call at all — not even count_tokens."""
    # Orthogonal to the query vector => distance 1.0, above chat_max_distance 0.5.
    dataset = _seed_corpus(chat_db, texts=["unrelated"], vector=(0.0, 1.0, 0.0, 0.0))
    client = FakeAnthropic()

    turn = prepare_turn(
        chat_db,
        request=ChatMessageRequest(dataset_id=dataset.id, message="anything"),
        embedding_client=StubEmbeddingClient(),
        settings=settings,
        client=client,
    )

    assert turn.refusal == NO_RELEVANT_FEEDBACK_ANSWER
    assert turn.retrieved == ()
    assert client.call_count == 0


def test_prepare_turn_without_a_client_raises_only_when_claude_is_needed(chat_db, settings):
    dataset = _seed_corpus(chat_db, texts=["checkout failed"])

    with pytest.raises(LlmUnavailableError):
        prepare_turn(
            chat_db,
            request=ChatMessageRequest(dataset_id=dataset.id, message="q"),
            embedding_client=StubEmbeddingClient(),
            settings=settings,
            client=None,
        )


def test_prepare_turn_refusal_needs_no_client(chat_db, settings):
    """An unconfigured key must not turn a legitimate refusal into a 503."""
    dataset = _seed_corpus(chat_db, texts=["unrelated"], vector=(0.0, 1.0, 0.0, 0.0))

    turn = prepare_turn(
        chat_db,
        request=ChatMessageRequest(dataset_id=dataset.id, message="q"),
        embedding_client=StubEmbeddingClient(),
        settings=settings,
        client=None,
    )

    assert turn.refusal is not None


def test_prepare_turn_replays_prior_turns(chat_db, settings):
    dataset = _seed_corpus(chat_db, texts=["checkout failed"])
    conversation = Conversation(dataset_id=dataset.id)
    chat_db.add(conversation)
    chat_db.flush()
    chat_db.add_all(
        [
            ChatMessage(
                conversation_id=conversation.id,
                role=ChatRole.USER,
                content="earlier question",
                sequence=0,
            ),
            ChatMessage(
                conversation_id=conversation.id,
                role=ChatRole.ASSISTANT,
                content="earlier answer",
                sequence=1,
            ),
        ]
    )
    chat_db.commit()

    turn = prepare_turn(
        chat_db,
        request=ChatMessageRequest(
            dataset_id=dataset.id, message="follow-up", conversation_id=conversation.id
        ),
        embedding_client=StubEmbeddingClient(),
        settings=settings,
        client=FakeAnthropic(),
    )

    assert [m["content"] for m in turn.history] == ["earlier question", "earlier answer"]
    assert turn.assistant_sequence == 3  # user turn took sequence 2


# --- stream_turn ------------------------------------------------------------


def _prepared(**overrides) -> PreparedTurn:
    base = {
        "conversation_id": uuid.uuid4(),
        "question": "why?",
        "retrieved": (_item("checkout failed with an error", 0),),
        "history": (),
        "assistant_sequence": 1,
        "refusal": None,
    }
    base.update(overrides)
    return PreparedTurn(**base)


def _conversation(session_factory) -> uuid.UUID:
    session = session_factory()
    try:
        dataset = Dataset(filename="c.csv")
        session.add(dataset)
        session.flush()
        conversation = Conversation(dataset_id=dataset.id)
        session.add(conversation)
        session.commit()
        return conversation.id
    finally:
        session.close()


def test_stream_turn_emits_tokens_then_citations_then_done(session_factory, settings):
    """AC 1: strict event ordering."""
    turn = _prepared(conversation_id=_conversation(session_factory))
    client = FakeAnthropic(["Checkout ", "fails [1]."])

    events = list(
        stream_turn(turn, settings=settings, client=client, session_factory=session_factory)
    )

    assert [e.event for e in events] == ["token", "token", "citations", "done"]
    assert events[2].data.items[0].feedback_item_id == turn.retrieved[0].id
    assert events[3].data.conversation_id == turn.conversation_id


def test_stream_turn_sends_the_configured_model_and_no_sampling_params(
    session_factory, settings
):
    """AC 8 + AC 9 as runtime facts, stronger than a grep."""
    turn = _prepared(conversation_id=_conversation(session_factory))
    client = FakeAnthropic(["ok [1]"])

    list(stream_turn(turn, settings=settings, client=client, session_factory=session_factory))

    kwargs = client.messages.stream_calls[0]
    assert kwargs["model"] == "claude-haiku-4-5"
    assert not {"temperature", "top_p", "top_k"} & kwargs.keys()
    assert kwargs["system"] == CHAT_SYSTEM_PROMPT
    assert kwargs["max_tokens"] == settings.chat_max_tokens


def test_stream_turn_refusal_streams_the_answer_without_calling_claude(
    session_factory, settings
):
    """AC 5 at the orchestration level."""
    turn = _prepared(
        conversation_id=_conversation(session_factory),
        retrieved=(),
        refusal=NO_RELEVANT_FEEDBACK_ANSWER,
    )
    client = FakeAnthropic()

    events = list(
        stream_turn(turn, settings=settings, client=client, session_factory=session_factory)
    )

    assert [e.event for e in events] == ["token", "citations", "done"]
    assert events[0].data.text == NO_RELEVANT_FEEDBACK_ANSWER
    assert events[1].data.items == []
    assert client.call_count == 0


def test_stream_turn_error_emits_error_and_nothing_after(session_factory, settings):
    """AC 11: an error frame, then the stream ends — no citations, no done."""
    turn = _prepared(conversation_id=_conversation(session_factory))
    client = FakeAnthropic(["partial ", "more"], fail_at=1)

    events = list(
        stream_turn(turn, settings=settings, client=client, session_factory=session_factory)
    )

    assert [e.event for e in events] == ["token", "error"]
    assert "could not be completed" in events[-1].data.message


def test_stream_turn_persists_the_assistant_message(session_factory, settings):
    turn = _prepared(conversation_id=_conversation(session_factory))
    client = FakeAnthropic(["Grounded answer [1]."])

    events = list(
        stream_turn(turn, settings=settings, client=client, session_factory=session_factory)
    )

    session = session_factory()
    try:
        stored = session.get(ChatMessage, events[-1].data.message_id)
        assert stored is not None
        assert stored.role == ChatRole.ASSISTANT
        assert stored.content == "Grounded answer [1]."
        assert stored.citations is not None
        assert stored.sequence == 1
    finally:
        session.close()


def test_stream_turn_does_not_persist_on_failure(session_factory, settings):
    """Persisting before the citations frame means a failure leaves no assistant row."""
    turn = _prepared(conversation_id=_conversation(session_factory))
    client = FakeAnthropic(["x"], fail_at=0)

    list(stream_turn(turn, settings=settings, client=client, session_factory=session_factory))

    session = session_factory()
    try:
        assert session.query(ChatMessage).count() == 0
    finally:
        session.close()


def test_stream_turn_stores_null_citations_when_none_were_cited(session_factory, settings):
    turn = _prepared(conversation_id=_conversation(session_factory))
    client = FakeAnthropic(["An answer with no citation markers."])

    events = list(
        stream_turn(turn, settings=settings, client=client, session_factory=session_factory)
    )

    assert events[-2].data.items == []
    session = session_factory()
    try:
        assert session.get(ChatMessage, events[-1].data.message_id).citations is None
    finally:
        session.close()


def test_stream_turn_citations_survive_a_split_token_boundary(session_factory, settings):
    """Parsing the accumulated answer, not each chunk: `[1]` arrives split."""
    turn = _prepared(conversation_id=_conversation(session_factory))
    client = FakeAnthropic(["Checkout fails [", "1", "]."])

    events = list(
        stream_turn(turn, settings=settings, client=client, session_factory=session_factory)
    )

    citations = events[-2].data.items
    assert len(citations) == 1
    assert citations[0].feedback_item_id == turn.retrieved[0].id


def test_stream_turn_includes_history_before_the_current_question(session_factory, settings):
    turn = _prepared(
        conversation_id=_conversation(session_factory),
        history=({"role": "user", "content": "earlier"}, {"role": "assistant", "content": "prior"}),
    )
    client = FakeAnthropic(["ok"])

    list(stream_turn(turn, settings=settings, client=client, session_factory=session_factory))

    messages = client.messages.stream_calls[0]["messages"]
    assert [m["content"] for m in messages[:2]] == ["earlier", "prior"]
    assert messages[-1]["role"] == "user"
    assert "Question: why?" in messages[-1]["content"]
