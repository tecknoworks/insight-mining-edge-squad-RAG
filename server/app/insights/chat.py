"""Chat-with-data orchestration: prepare a turn, stream it, persist it.

Split into two phases on purpose.

``prepare_turn`` does everything that can *fail* — dataset lookup, query
embedding, retrieval, the relevance floor, history truncation, prompt assembly
— and it runs inside the request's dependency resolution, before a single byte
of the response has been sent. Once a streaming response has started, headers
are gone and ``HTTPException`` is useless, so every 4xx/5xx must be decided
here.

That split also makes the anti-hallucination guardrail structural rather than
merely tested: when nothing clears the relevance floor, ``prepare_turn`` sets
``refusal`` and ``stream_turn`` never touches the Anthropic client at all —
not even for ``count_tokens``.

``stream_turn`` yields transport-neutral :class:`ChatEvent` values; turning
those into SSE frames is the API layer's job.
"""

import logging
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, cast

from anthropic import Anthropic, APIConnectionError, APIStatusError, RateLimitError
from anthropic.types import MessageParam
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.embeddings.client import EmbeddingClient
from app.insights.citations import build_citations
from app.insights.prompts import (
    CHAT_SYSTEM_PROMPT,
    NO_RELEVANT_FEEDBACK_ANSWER,
    build_user_message,
)
from app.insights.retrieval import RetrievedItem, retrieve
from app.models.db import ChatMessage, Conversation, Dataset
from app.models.schemas import (
    ChatCitation,
    ChatCitationsEvent,
    ChatDoneEvent,
    ChatErrorEvent,
    ChatMessageRequest,
    ChatRole,
    ChatTokenEvent,
)

logger = logging.getLogger(__name__)

# Rough chars-per-token for the local pre-selection pass. Deliberately
# pessimistic (real English is ~4) so the local estimate over-counts and the
# authoritative `count_tokens` check below rarely has to drop more.
_CHARS_PER_TOKEN = 3.5

# How many times we re-verify after dropping turns. Each iteration is an HTTP
# round-trip, so this is bounded rather than a while-loop.
_MAX_HISTORY_VERIFY_PASSES = 3


class DatasetNotFoundError(Exception):
    """The requested dataset does not exist."""


class ConversationNotFoundError(Exception):
    """The requested conversation does not exist, or belongs to another dataset."""


class LlmUnavailableError(Exception):
    """A Claude call is required for this turn but no API key is configured."""


@dataclass(frozen=True)
class ChatEvent:
    """One SSE frame, before transport encoding. ``event`` is the SSE event name."""

    event: str
    data: BaseModel


@dataclass(frozen=True)
class PreparedTurn:
    """Everything needed to stream one answer, with all fallible work already done."""

    conversation_id: uuid.UUID
    question: str
    retrieved: tuple[RetrievedItem, ...]
    history: tuple[dict[str, Any], ...]
    assistant_sequence: int
    # When set, the answer is this text and Claude is never called.
    refusal: str | None = None


def _estimate_tokens(messages: Sequence[dict[str, Any]]) -> int:
    """Cheap local token estimate, used to pre-select before verifying once."""
    characters = sum(len(str(message.get("content", ""))) for message in messages)
    return int(characters / _CHARS_PER_TOKEN)


def truncate_history(
    history: Sequence[dict[str, Any]],
    *,
    max_tokens: int,
    client: Anthropic,
    model: str,
) -> list[dict[str, Any]]:
    """Trim prior turns to fit ``max_tokens``, dropping the oldest first.

    Drops whole ``(user, assistant)`` pairs so the turn structure stays intact
    and the result never begins with an ``assistant`` message — the Messages
    API requires the first message to be ``user``.

    Selection is by local estimate; the result is then verified with a single
    ``count_tokens`` call, retried a bounded number of times if it is still
    over. Note this deliberately does *not* call ``count_tokens`` once per
    message the way ``summarizer._sample_cluster_items`` does — that is one
    HTTPS round-trip per item.
    """
    trimmed = list(history)

    # Drop from the front in pairs until the local estimate fits.
    while trimmed and _estimate_tokens(trimmed) > max_tokens:
        del trimmed[:2]

    for _ in range(_MAX_HISTORY_VERIFY_PASSES):
        if not trimmed:
            return []
        actual = client.messages.count_tokens(
            model=model,
            messages=trimmed,  # type: ignore[arg-type]
        ).input_tokens
        if actual <= max_tokens:
            return trimmed
        logger.info(
            "chat history still %d tokens (budget %d) — dropping the oldest turn",
            actual,
            max_tokens,
        )
        del trimmed[:2]

    return trimmed


def _load_history(db: Session, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    """Load prior turns as Anthropic message params, ordered by ``sequence``."""
    rows = (
        db.execute(
            select(ChatMessage.role, ChatMessage.content)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.sequence)
        )
        .all()
    )
    messages = [{"role": row.role.value, "content": row.content} for row in rows]

    # A leading assistant turn would be rejected by the Messages API. This
    # should not happen, but a partially-persisted turn (client disconnected
    # mid-stream) could in principle leave one.
    while messages and messages[0]["role"] != ChatRole.USER.value:
        logger.warning(
            "chat history for %s starts with an assistant turn; dropping it", conversation_id
        )
        del messages[0]
    return messages


def prepare_turn(
    db: Session,
    *,
    request: ChatMessageRequest,
    embedding_client: EmbeddingClient,
    settings: Settings,
    client: Anthropic | None,
) -> PreparedTurn:
    """Resolve, retrieve, and assemble one turn. Commits the user message.

    The user message is committed here rather than alongside the answer so a
    client that disconnects mid-stream still keeps its question.

    Raises:
        DatasetNotFoundError: No such dataset.
        ConversationNotFoundError: No such conversation, or it belongs to a
            different dataset.
        LlmUnavailableError: Claude is needed for this turn but unconfigured.
    """
    if db.get(Dataset, request.dataset_id) is None:
        raise DatasetNotFoundError(f"dataset {request.dataset_id} not found")

    if request.conversation_id is None:
        conversation = Conversation(dataset_id=request.dataset_id, title=request.message[:80])
        db.add(conversation)
        db.flush()
        history: list[dict[str, Any]] = []
    else:
        existing = db.get(Conversation, request.conversation_id)
        if existing is None:
            raise ConversationNotFoundError(f"conversation {request.conversation_id} not found")
        conversation = existing
        if conversation.dataset_id != request.dataset_id:
            # Answering inside a conversation bound to another dataset would
            # mix corpora; refuse rather than silently re-scope.
            raise ConversationNotFoundError(
                f"conversation {conversation.id} does not belong to dataset {request.dataset_id}"
            )
        history = _load_history(db, conversation.id)

    # Same model and the query code path — a mismatch here silently degrades
    # retrieval quality with no error anywhere.
    query_vector = embedding_client.embed_query(request.message)

    retrieved = retrieve(
        db,
        dataset_id=request.dataset_id,
        query_vector=query_vector,
        filters=request.filters,
        top_k=settings.chat_top_k,
        max_distance=settings.chat_max_distance,
        dimension=settings.embedding_dimension,
    )

    refusal = None if retrieved else NO_RELEVANT_FEEDBACK_ANSWER
    if refusal is None and client is None:
        raise LlmUnavailableError("Anthropic API key not configured")

    if refusal is None:
        assert client is not None  # narrowed by the check above
        history = truncate_history(
            history,
            max_tokens=settings.chat_max_history_tokens,
            client=client,
            model=settings.anthropic_chat_model,
        )
    else:
        # Nothing will be sent to Claude, so don't spend a count_tokens
        # round-trip on history we won't use.
        history = []

    next_sequence = (
        db.execute(
            select(func.coalesce(func.max(ChatMessage.sequence), -1)).where(
                ChatMessage.conversation_id == conversation.id
            )
        ).scalar_one()
        + 1
    )

    db.add(
        ChatMessage(
            conversation_id=conversation.id,
            role=ChatRole.USER,
            content=request.message,
            sequence=next_sequence,
        )
    )
    db.commit()

    return PreparedTurn(
        conversation_id=conversation.id,
        question=request.message,
        retrieved=tuple(retrieved),
        history=tuple(history),
        assistant_sequence=next_sequence + 1,
        refusal=refusal,
    )


def persist_assistant_turn(
    session_factory: Callable[[], Session],
    turn: PreparedTurn,
    answer: str,
    citations: Sequence[ChatCitation],
) -> uuid.UUID:
    """Write the assistant message in its own short-lived session.

    The request-scoped session's lifetime relative to a streaming response body
    is a FastAPI-internal detail, so this owns its session outright — the same
    reasoning ``embeddings.service.run_job`` documents for background work.
    """
    db = session_factory()
    try:
        message = ChatMessage(
            conversation_id=turn.conversation_id,
            role=ChatRole.ASSISTANT,
            content=answer,
            citations=[citation.model_dump(mode="json") for citation in citations] or None,
            sequence=turn.assistant_sequence,
        )
        db.add(message)
        db.commit()
        return message.id
    finally:
        db.close()


def _failure_message(exc: Exception) -> str:
    """A user-facing reason, without leaking internals into the stream."""
    if isinstance(exc, RateLimitError):
        return "API rate limit exceeded"
    if isinstance(exc, APIConnectionError):
        return "Could not reach the language model"
    if isinstance(exc, APIStatusError):
        return f"Language model error (HTTP {exc.status_code})"
    return "The answer could not be completed"


def stream_turn(
    turn: PreparedTurn,
    *,
    settings: Settings,
    client: Anthropic | None,
    session_factory: Callable[[], Session],
) -> Iterator[ChatEvent]:
    """Stream one answer as ``token*`` → ``citations`` → ``done``.

    On failure, yields a single ``error`` frame and stops — never ``done``, and
    never ``citations``. Persistence happens *before* the citations frame so a
    write failure cannot produce an ``error`` after it.

    Every exception is swallowed into an ``error`` frame: the response has
    already begun, so an escaping exception would truncate the stream and leave
    the client hanging.
    """
    try:
        if turn.refusal is not None:
            answer = turn.refusal
            yield ChatEvent("token", ChatTokenEvent(text=answer))
            citations: list[ChatCitation] = []
        else:
            assert client is not None  # prepare_turn raises if it would be needed and None
            chunks: list[str] = []
            messages = cast(
                "list[MessageParam]",
                [
                    *turn.history,
                    {"role": "user", "content": build_user_message(turn.question, turn.retrieved)},
                ],
            )
            with client.messages.stream(
                model=settings.anthropic_chat_model,
                max_tokens=settings.chat_max_tokens,
                system=CHAT_SYSTEM_PROMPT,
                messages=messages,
                # No temperature/top_p/top_k: accepted on Haiku but rejected
                # with 400 on Sonnet 5 and Opus 4.7+, and the model is
                # env-configurable. Omitting them keeps the env var switchable
                # without a code change.
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
                    yield ChatEvent("token", ChatTokenEvent(text=text))
                final = stream.get_final_message()

            logger.info(
                "chat turn %s: %d input, %d output tokens (stop_reason=%s)",
                turn.conversation_id,
                final.usage.input_tokens,
                final.usage.output_tokens,
                final.stop_reason,
            )
            if final.stop_reason == "max_tokens":
                logger.warning("chat answer for %s truncated at max_tokens", turn.conversation_id)

            answer = "".join(chunks)
            # Citations are parsed from the accumulated answer, never per
            # chunk — a token boundary splits `[12]` into `[1` and `2]`.
            citations = build_citations(answer, turn.retrieved)

        message_id = persist_assistant_turn(session_factory, turn, answer, citations)

        yield ChatEvent("citations", ChatCitationsEvent(items=citations))
        yield ChatEvent(
            "done",
            ChatDoneEvent(conversation_id=turn.conversation_id, message_id=message_id),
        )
    except Exception as exc:  # noqa: BLE001 — must never escape a started response
        logger.exception("chat stream failed for conversation %s", turn.conversation_id)
        yield ChatEvent("error", ChatErrorEvent(message=_failure_message(exc)))
