"""Citation extraction for grounded chat answers.

Pure functions only — no database, no Anthropic client — so the whole
answer-to-provenance path is unit-testable without mocks.

The system prompt tells the model to reference retrieved items by a 1-based
numeric index. This module turns the indices it *actually wrote* into validated
citations. Provenance is never taken on trust: it mirrors the discipline
``summarizer._validate_quotes`` applies to quotes — an index the model invented
is dropped and logged, never guessed at.
"""

import logging
import re
from collections.abc import Sequence

from app.insights.retrieval import RetrievedItem
from app.models.schemas import ChatCitation

logger = logging.getLogger(__name__)

# Per the PRD's citation contract.
EXCERPT_MAX_LEN = 200

# Matches `[3]` and grouped forms like `[1, 4, 5]` — the citation style the
# system prompt asks for. Deliberately narrow: prose forms ("item 3") are not
# matched, because disambiguating them costs more than the recall is worth.
# The prompt is what makes the bracket form reliable.
_CITATION_PATTERN = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")


def truncate_text(text: str, max_len: int, *, word_boundary: bool = False) -> tuple[str, bool]:
    """Truncate ``text`` to ``max_len``, appending … if it was shortened.

    Args:
        text: Text to truncate.
        max_len: Maximum length, excluding the appended ellipsis.
        word_boundary: When true, cut back to the last whitespace instead of
            mid-word. Off by default so existing callers keep a hard cut.

    Returns:
        Tuple of (possibly truncated text, whether it was truncated).
    """
    if len(text) <= max_len:
        return text, False

    cut = text[:max_len]
    if word_boundary:
        spaced = cut.rsplit(" ", 1)[0]
        # Only accept the word-boundary cut if it kept something meaningful —
        # a single very long token would otherwise truncate to the empty string.
        if spaced:
            cut = spaced
    return cut.rstrip() + "…", True


def parse_cited_indices(answer: str, item_count: int) -> list[int]:
    """Extract the 1-based item indices an answer referenced, in order of appearance.

    Must be given the *accumulated* answer, never an individual streamed chunk:
    a token boundary will split ``[12]`` into ``[1`` and ``2]``.

    Out-of-range indices are dropped with a warning — that is the model citing
    an item it was never shown. Duplicates collapse to their first appearance.

    Args:
        answer: The complete answer text.
        item_count: How many items were actually retrieved and numbered.

    Returns:
        Valid, de-duplicated indices in first-appearance order.
    """
    seen: list[int] = []
    for group in _CITATION_PATTERN.findall(answer):
        for raw in group.split(","):
            index = int(raw.strip())
            if index < 1 or index > item_count:
                logger.warning(
                    "chat answer cited item [%d] but only %d items were retrieved; dropping",
                    index,
                    item_count,
                )
                continue
            if index not in seen:
                seen.append(index)
    return seen


def build_citations(answer: str, retrieved: Sequence[RetrievedItem]) -> list[ChatCitation]:
    """Map the indices an answer cited back to the feedback items behind them.

    Every returned ``feedback_item_id`` comes from ``retrieved``, which was
    built by a dataset-scoped SQL query — so "every cited id belongs to the
    requested dataset" holds by construction, not by validation.

    An answer that cited nothing yields an empty list. It deliberately does not
    fall back to "all retrieved items": the citations event reports what the
    answer *used*, and padding it would misreport provenance.
    """
    citations: list[ChatCitation] = []
    for index in parse_cited_indices(answer, len(retrieved)):
        item = retrieved[index - 1]
        excerpt, _ = truncate_text(item.feedback_text, EXCERPT_MAX_LEN, word_boundary=True)
        citations.append(
            ChatCitation(
                feedback_item_id=item.id,
                excerpt=excerpt,
                source=item.source,
                date=item.submitted_at,
            )
        )

    if not citations:
        logger.info("chat answer cited no retrieved items")
    return citations
