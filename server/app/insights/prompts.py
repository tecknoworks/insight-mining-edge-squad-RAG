"""Prompt text for chat-with-data.

Every string Claude sees on the chat path lives here — never in
``app/api/chat.py``. Keeping it in one module means a reviewer can read the
whole instruction surface in one place, and grep can prove the API layer holds
no prompt text.

The context-block format matches the one ``summarizer`` already uses
(``Feedback:`` / ``Source:`` / ``Date:``), so both Claude stages see feedback
rendered the same way.
"""

from collections.abc import Sequence

from app.insights.retrieval import RetrievedItem

# Answers must be grounded, and the model must be willing to say the corpus
# does not cover the question. The numbered-citation instruction is what makes
# `citations.parse_cited_indices` reliable — it is load-bearing, not cosmetic.
CHAT_SYSTEM_PROMPT = """\
You are a customer-feedback analyst. You answer questions about a corpus of \
customer feedback using ONLY the numbered feedback items supplied in the user \
message.

Rules:
1. Base every claim on the supplied feedback items. Do not use outside \
knowledge about the product, the company, or the market.
2. Cite the items supporting each claim with their bracketed numbers, like \
[1] or [2, 5]. Cite the items you actually relied on.
3. If the supplied feedback does not cover the question, say so plainly — for \
example "The feedback doesn't cover pricing." Do not speculate, and do not pad \
the answer with loosely related themes to appear helpful.
4. Report what the feedback says, including how widely a view appears. Never \
invent counts, percentages, or trends that the items do not support.
5. Be concise and specific. Prefer naming the concrete complaint over \
abstract summary language.
"""

# Returned when retrieval finds nothing within the relevance floor. This path
# never reaches Claude, so the text has to stand on its own.
NO_RELEVANT_FEEDBACK_ANSWER = (
    "I don't have feedback about that. Nothing in this dataset is closely "
    "related to your question — try rephrasing it, widening the date range, "
    "or removing the source filter."
)


def format_context_block(items: Sequence[RetrievedItem]) -> str:
    """Render retrieved items as the numbered context block for the prompt.

    Numbering is 1-based and positional: item *n* in this block is
    ``items[n - 1]``, which is the contract ``citations`` relies on to map a
    cited index back to a ``feedback_item_id``. Never renumber after prompting.

    ``source`` and ``date`` are included when present so channel and temporal
    questions ("what are support tickets saying this month") can be answered.
    """
    blocks: list[str] = []
    for position, item in enumerate(items, start=1):
        block = f"[{position}] Feedback: {item.feedback_text}"
        if item.source:
            block += f"\nSource: {item.source}"
        if item.submitted_at:
            block += f"\nDate: {item.submitted_at.isoformat()}"
        blocks.append(block)
    return "\n\n".join(blocks)


def build_user_message(question: str, items: Sequence[RetrievedItem]) -> str:
    """Assemble the user turn: the numbered feedback, then the question."""
    return (
        f"Feedback items:\n\n{format_context_block(items)}\n\n"
        f"Question: {question}"
    )
