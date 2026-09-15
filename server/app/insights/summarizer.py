"""Claude-powered cluster summarization — on-demand generation + caching.

Fetches cluster feedback, samples deterministically, calls Claude with structured
output to generate a label, summary, and representative quotes. Validates every
quote as an exact substring of feedback text. Stores results in cache with TTL.
"""

import json
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from anthropic import Anthropic
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.insights.citations import truncate_text
from app.models.db import Cluster, ClusterAssignment, ClusterSummary, FeedbackItem

logger = logging.getLogger(__name__)

# JSON schema for Claude structured output
SUMMARIZATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "description": "Theme label, 2–5 words, title case",
            "minLength": 1,
            "maxLength": 50,
        },
        "summary": {
            "type": "string",
            "description": (
                "Plain-language summary, 2–4 sentences, "
                "explaining the theme and why it matters"
            ),
            "minLength": 10,
            "maxLength": 500,
        },
        "quotes": {
            "type": "array",
            "items": {
                "type": "string",
                "description": "Verbatim quote from feedback, up to 500 chars",
                "maxLength": 500,
            },
            "minItems": 3,
            "maxItems": 5,
            "description": "3–5 representative quotes from the cluster",
        },
    },
    "required": ["label", "summary", "quotes"],
    "additionalProperties": False,
}


def _sample_cluster_items(
    db: Session, cluster_id: uuid.UUID, max_tokens: int, client: Anthropic, model: str
) -> list[FeedbackItem]:
    """Sample feedback items from a cluster, deterministically and within token budget.

    Uses cluster_id as seed for reproducibility. Samples via token count, not row count,
    using count_tokens to stay within max_tokens budget.

    Args:
        db: Database session.
        cluster_id: Cluster to sample from.
        max_tokens: Token budget for the sample.
        client: Anthropic client for counting tokens.
        model: Model ID for token counting.

    Returns:
        List of sampled feedback items.

    Raises:
        ValueError: If cluster has no items.
    """
    # Fetch all items in cluster
    items = db.execute(
        select(FeedbackItem)
        .join(
            ClusterAssignment,
            and_(
                ClusterAssignment.feedback_item_id == FeedbackItem.id,
                ClusterAssignment.cluster_id == cluster_id,
            ),
        )
        .order_by(FeedbackItem.id)  # Deterministic ordering
    ).scalars().all()

    if not items:
        raise ValueError(f"cluster {cluster_id} has no items")

    # Seed RNG deterministically by cluster_id
    seed = int(cluster_id.int % (2**31 - 1))
    rng = random.Random(seed)
    rng.shuffle(items)

    # Greedily sample items within token budget
    sample = []
    token_count = 0
    reserve = 500  # Reserve tokens for prompt structure/response formatting

    for item in items:
        # Format the item with optional fields
        item_text = f"Feedback: {item.feedback_text}"
        if item.source:
            item_text += f"\nSource: {item.source}"
        if item.submitted_at:
            item_text += f"\nDate: {item.submitted_at.isoformat()}"

        # Count tokens for this item
        item_tokens = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": item_text}],
        ).input_tokens

        if token_count + item_tokens + reserve <= max_tokens:
            sample.append(item)
            token_count += item_tokens

    if not sample:
        # Token budget too small; use at least one item
        sample = [items[0]]

    return sample


def _truncate_quote(quote: str, max_len: int = 500) -> tuple[str, bool]:
    """Truncate a quote to max length, appending … if truncated.

    Delegates to the shared helper in ``app.insights.citations``, which the
    chat path also uses (at a shorter limit, and cutting on word boundaries).

    Args:
        quote: Quote text.
        max_len: Maximum length (default 500).

    Returns:
        Tuple of (truncated_quote, was_truncated).
    """
    return truncate_text(quote, max_len)


def _validate_quotes(
    quotes: list[str], cluster_items: dict[uuid.UUID, str]
) -> tuple[list[tuple[str, uuid.UUID]], list[str]]:
    """Validate that each quote is an exact substring of a cluster item.

    Args:
        quotes: List of quotes from Claude.
        cluster_items: Dict mapping feedback_item_id to feedback_text.

    Returns:
        Tuple of (valid_quotes, invalid_quotes) where valid_quotes is a list of
        (quote, feedback_item_id) tuples and invalid_quotes is a list of unmatched quotes.
    """
    valid = []
    invalid = []

    for quote in quotes:
        # Find which item this quote came from (exact substring match)
        found = False
        for item_id, item_text in cluster_items.items():
            if quote in item_text:
                valid.append((quote, item_id))
                found = True
                break

        if not found:
            invalid.append(quote)

    return valid, invalid


def generate_cluster_summary(
    db: Session,
    cluster_id: uuid.UUID,
    settings: Settings,
    client: Anthropic,
    retry_count: int = 0,
) -> dict[str, object]:
    """Generate a summary for a cluster using Claude.

    Samples cluster items, constructs a prompt, calls Claude with structured output,
    validates quotes, and returns the result. Retries once if quote validation fails.

    Args:
        db: Database session.
        cluster_id: Cluster to summarize.
        settings: Application settings (for model ID, token limits).
        client: Anthropic client.
        retry_count: Internal retry counter (0 on first call, incremented on retry).

    Returns:
        Dict with keys: label, summary, quotes (list of {text, feedback_item_id}).

    Raises:
        ValueError: If cluster not found, empty, or validation fails after retry.
    """
    if retry_count > 1:
        raise ValueError(
            "Failed to generate valid summary after retries: quotes not found in cluster items"
        )

    # Fetch cluster
    cluster = db.get(Cluster, cluster_id)
    if cluster is None:
        raise ValueError(f"cluster {cluster_id} not found")

    # Sample items
    sample = _sample_cluster_items(
        db,
        cluster_id,
        settings.summarization_max_sample_tokens,
        client,
        settings.anthropic_summarization_model,
    )

    # Build a map of item IDs to text for quote validation
    cluster_items_map = {item.id: item.feedback_text for item in sample}

    # Construct prompt
    sample_text = "\n\n".join(
        [
            (
                f"Feedback: {item.feedback_text}"
                + (f"\nSource: {item.source}" if item.source else "")
                + (f"\nDate: {item.submitted_at.isoformat()}" if item.submitted_at else "")
            )
            for item in sample
        ]
    )

    prompt = f"""Analyze this cluster of customer feedback and provide:
1. A concise 2–5 word theme label (title case)
2. A 2–4 sentence summary explaining what the theme is and why it matters
3. 3–5 verbatim quotes from the feedback below that best represent the theme

IMPORTANT: Every quote must be an exact, verbatim substring from the feedback below.
Do not paraphrase, summarize, or create new text. Copy exactly as written.

Feedback in this cluster:
{sample_text}

Respond with only a JSON object matching the schema provided."""

    # Call Claude with structured output
    try:
        response = client.messages.create(
            model=settings.anthropic_summarization_model,
            max_tokens=settings.summarization_max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=1,  # Required for structured output
            output_config={
                "type": "json_schema",
                "json_schema": {
                    "name": "ClusterSummary",
                    "schema": SUMMARIZATION_RESPONSE_SCHEMA,
                    "strict": True,
                },
            },
        )
    except Exception as exc:
        logger.error(
            f"Claude API call failed for cluster {cluster_id}: {type(exc).__name__}: {exc}"
        )
        raise ValueError(f"Claude API error: {str(exc)}") from exc

    # Log token usage
    logger.info(
        f"Cluster {cluster_id} summary: {response.usage.input_tokens} input, "
        f"{response.usage.output_tokens} output tokens"
    )

    # Handle stop reasons
    if response.stop_reason == "end_turn":
        pass  # Normal completion
    elif response.stop_reason == "refusal":
        raise ValueError("Claude refused to summarize this cluster")
    elif response.stop_reason == "max_tokens":
        raise ValueError("Summary generation hit token limit")
    else:
        raise ValueError(f"Unexpected stop reason: {response.stop_reason}")

    # Parse response
    try:
        result = json.loads(response.content[0].text)
    except (json.JSONDecodeError, IndexError, KeyError) as exc:
        raise ValueError(f"Failed to parse Claude response: {exc}") from exc

    # Truncate quotes and build quote list
    truncated_quotes = []
    for q in result["quotes"]:
        truncated_q, was_truncated = _truncate_quote(q)
        truncated_quotes.append(truncated_q)

    # Validate quotes against actual feedback items
    valid_quotes, invalid_quotes = _validate_quotes(truncated_quotes, cluster_items_map)

    if len(valid_quotes) < 3 and not invalid_quotes:
        # All quotes validated, proceed
        pass
    elif invalid_quotes:
        # Some quotes don't match; retry once
        if retry_count == 0:
            logger.warning(
                f"Cluster {cluster_id}: {len(invalid_quotes)} quotes failed validation, retrying"
            )
            return generate_cluster_summary(db, cluster_id, settings, client, retry_count=1)
        else:
            raise ValueError(
                f"After retry, {len(invalid_quotes)} quotes not found in cluster items"
            )

    # Return validated result
    return {
        "label": result["label"],
        "summary": result["summary"],
        "quotes": [{"text": quote_text, "feedback_item_id": str(item_id)}
                   for quote_text, item_id in valid_quotes],
    }


def get_or_generate_cluster_summary(
    db: Session,
    cluster_id: uuid.UUID,
    settings: Settings,
    client: Anthropic,
    force: bool = False,
) -> dict[str, object]:
    """Fetch cached cluster summary or generate it on-demand.

    Checks the cache; if hit and not forced, returns cached result immediately.
    Otherwise, generates via Claude, stores in cache, and returns.

    Args:
        db: Database session.
        cluster_id: Cluster to summarize.
        settings: Application settings.
        client: Anthropic client.
        force: If True, bypass cache and regenerate.

    Returns:
        Dict with keys: cluster_id, label, summary, quotes, cached_at (ISO 8601 string).

    Raises:
        ValueError: If cluster not found, empty, or Claude call fails.
    """
    # Check cache
    cached = db.get(ClusterSummary, cluster_id)
    age = datetime.now(UTC).replace(tzinfo=None) - cached.created_at if cached else None

    if cached and not force and age and age <= timedelta(hours=settings.summary_cache_ttl_hours):
        # Cache hit; return it
        logger.info(f"Cluster {cluster_id} summary served from cache")
        return {
            "cluster_id": str(cluster_id),
            "label": cached.label,
            "summary": cached.summary,
            "quotes": cached.quotes,
            "cached_at": cached.created_at.isoformat(),
        }

    # Generate new summary
    result = generate_cluster_summary(db, cluster_id, settings, client)

    # Store in cache
    now = datetime.now(UTC).replace(tzinfo=None)
    summary = ClusterSummary(
        cluster_id=cluster_id,
        label=result["label"],
        summary=result["summary"],
        quotes=result["quotes"],
        created_at=now,
    )
    db.merge(summary)
    db.commit()

    logger.info(f"Cluster {cluster_id} summary cached")

    return {
        "cluster_id": str(cluster_id),
        "label": result["label"],
        "summary": result["summary"],
        "quotes": result["quotes"],
        "cached_at": now.isoformat(),
    }
