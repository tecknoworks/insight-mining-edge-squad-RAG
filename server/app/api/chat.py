"""Chat-with-data routes.

Thin by design. Retrieval SQL lives in ``app.insights.retrieval``, prompt text
in ``app.insights.prompts``, and orchestration in ``app.insights.chat``; this
module only wires dependencies, maps domain errors to HTTP status codes, and
adapts the module layer's transport-neutral ``ChatEvent`` stream to SSE frames.

Everything that can fail is resolved in the ``resolve_turn`` dependency, which
runs *before* the response starts — once a stream has begun, headers are gone
and ``HTTPException`` no longer reaches the client.
"""

import uuid
from collections.abc import Iterator
from functools import lru_cache

from anthropic import Anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal, get_db
from app.embeddings.client import EmbeddingClient, get_embedding_client
from app.insights.chat import (
    ConversationNotFoundError,
    DatasetNotFoundError,
    LlmUnavailableError,
    PreparedTurn,
    prepare_turn,
    stream_turn,
)
from app.models.db import Conversation
from app.models.schemas import ChatMessageRequest, ConversationDetail

router = APIRouter(prefix="/chat", tags=["chat"])


@lru_cache
def get_anthropic_client() -> Anthropic | None:
    """Return a cached Anthropic client, or ``None`` when no key is configured.

    A FastAPI dependency rather than an inline constructor so tests can inject
    a fake and assert on the calls made — in particular that a turn which was
    short-circuited by the relevance floor made *no* calls at all.

    Returning ``None`` instead of raising keeps "unconfigured" a 503 decided by
    the caller, and the ``lru_cache`` means one pooled client per process
    instead of a fresh one per request.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    return Anthropic(api_key=settings.anthropic_api_key)


def resolve_turn(
    request: ChatMessageRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    anthropic_client: Anthropic | None = Depends(get_anthropic_client),
) -> PreparedTurn:
    """Do every fallible part of a turn while HTTP error responses are still possible."""
    try:
        return prepare_turn(
            db,
            request=request,
            embedding_client=embedding_client,
            settings=settings,
            client=anthropic_client,
        )
    except (DatasetNotFoundError, ConversationNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LlmUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post("/messages", response_class=EventSourceResponse)
def post_chat_message(
    turn: PreparedTurn = Depends(resolve_turn),
    settings: Settings = Depends(get_settings),
    anthropic_client: Anthropic | None = Depends(get_anthropic_client),
) -> Iterator[ServerSentEvent]:
    """Answer a question over the feedback corpus, streaming the answer as SSE.

    Emits ``token*`` → ``citations`` → ``done``; on failure a single ``error``
    frame and nothing after it. Note the stream also carries periodic ``:``
    keepalive comments, which clients must skip.

    A sync generator on purpose: the body blocks on the Anthropic HTTP stream
    and on SQLAlchemy, so FastAPI runs it in a threadpool rather than on the
    event loop.

    Returns:
        200 with an SSE stream.
        404 if the dataset or conversation does not exist.
        503 if a Claude call is required but no API key is configured.
    """
    for event in stream_turn(
        turn,
        settings=settings,
        client=anthropic_client,
        # The generator owns its own session for the final write; the
        # request-scoped one's lifetime across a streaming body is a
        # framework-internal detail we'd rather not depend on.
        session_factory=SessionLocal,
    ):
        yield ServerSentEvent(event=event.event, data=event.data)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Conversation:
    """Replay a conversation and its messages, ordered by ``sequence``.

    Returns:
        200 with the conversation and its messages.
        404 if the conversation does not exist.
    """
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found"
        )
    return conversation
