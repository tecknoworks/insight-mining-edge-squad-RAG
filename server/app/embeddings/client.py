"""Provider-agnostic embedding client.

Defines a narrow ``EmbeddingClient`` protocol and a ``sentence-transformers``
implementation behind it, so a future provider swap is a config + one-class
change. ``embed_documents``/``embed_query`` both call the same underlying
model — MiniLM has no separate document/query mode — matching the interface
IM-6 (chat retrieval) expects.
"""

import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class _Tokenizer(Protocol):
    """The slice of a ``transformers`` tokenizer's interface truncation needs."""

    def encode(self, text: str, add_special_tokens: bool = ...) -> list[int]: ...

    def decode(self, token_ids: list[int], skip_special_tokens: bool = ...) -> str: ...


def truncate_texts(
    texts: list[str],
    tokenizer: _Tokenizer,
    max_seq_length: int,
    ids: Sequence[str] | None = None,
) -> list[str]:
    """Truncate each text to ``max_seq_length`` tokens, logging when truncation occurs.

    A pure function of ``(texts, tokenizer, max_seq_length)`` — deterministic,
    and independent of any loaded model — so it is unit-testable with a fake
    tokenizer, with no real model load or network call required.
    """
    truncated_texts = []
    for index, text in enumerate(texts):
        token_ids = tokenizer.encode(text, add_special_tokens=True)
        if len(token_ids) <= max_seq_length:
            truncated_texts.append(text)
            continue
        truncated_ids = token_ids[:max_seq_length]
        truncated_text = tokenizer.decode(truncated_ids, skip_special_tokens=True)
        identifier = ids[index] if ids is not None else f"batch index {index}"
        logger.warning(
            "Truncated feedback text %s from %d to %d tokens before embedding",
            identifier,
            len(token_ids),
            max_seq_length,
        )
        truncated_texts.append(truncated_text)
    return truncated_texts


class EmbeddingClient(Protocol):
    """Narrow interface so a future provider swap is a config + one-class change.

    ``ids``, when given, must be the same length as ``texts`` and is used only
    to identify which feedback item a truncation warning refers to — it does
    not change what is returned.
    """

    def embed_documents(
        self, texts: list[str], *, ids: Sequence[str] | None = None
    ) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingModelConfigError(RuntimeError):
    """Raised when the configured model doesn't match what settings expect."""


class SentenceTransformerEmbeddingClient:
    """Wraps a single ``sentence-transformers`` model for documents and queries."""

    def __init__(self, model_name: str, expected_dimension: int) -> None:
        self._model = SentenceTransformer(model_name)
        actual_dimension = self._model.get_embedding_dimension()
        if actual_dimension != expected_dimension:
            raise EmbeddingModelConfigError(
                f"EMBEDDING_DIMENSION={expected_dimension} does not match "
                f"model '{model_name}''s actual output dimension ({actual_dimension})"
            )
        max_seq_length = self._model.max_seq_length
        if max_seq_length is None:
            raise EmbeddingModelConfigError(
                f"model '{model_name}' does not report a max_seq_length"
            )
        self._max_seq_length = max_seq_length

    def embed_documents(
        self, texts: list[str], *, ids: Sequence[str] | None = None
    ) -> list[list[float]]:
        truncated_texts = self._truncate(texts, ids)
        vectors = self._model.encode(truncated_texts, convert_to_numpy=True)
        return vectors.tolist()  # type: ignore[no-any-return]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def _truncate(self, texts: list[str], ids: Sequence[str] | None) -> list[str]:
        return truncate_texts(texts, self._model.tokenizer, self._max_seq_length, ids)


@lru_cache
def get_embedding_client() -> EmbeddingClient:
    """Return a cached embedding client (loads the model once per process)."""
    settings = get_settings()
    return SentenceTransformerEmbeddingClient(
        settings.embedding_model, settings.embedding_dimension
    )
