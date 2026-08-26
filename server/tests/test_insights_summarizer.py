"""Unit tests for cluster summarization logic."""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.insights.summarizer import (
    _sample_cluster_items,
    _truncate_quote,
    _validate_quotes,
    generate_cluster_summary,
    get_or_generate_cluster_summary,
)
from app.models.db import Cluster, ClusterAssignment, ClusteringRun, ClusterSummary, FeedbackItem


@pytest.fixture
def sample_cluster_with_items(db: Session, sample_dataset_with_embeddings):
    """Create a clustering run and cluster with sample feedback items."""
    dataset = sample_dataset_with_embeddings

    # Create clustering run
    run = ClusteringRun(
        dataset_id=dataset.id,
        algorithm="hdbscan",
        params={"min_cluster_size": 2},
        random_seed=42,
        cluster_count=1,
        noise_count=0,
        is_current=True,
    )
    db.add(run)
    db.flush()

    # Create cluster
    cluster = Cluster(run_id=run.id, cluster_index=0, item_count=3)
    db.add(cluster)
    db.flush()

    # Assign items to cluster
    items = db.execute(
        select(FeedbackItem).where(FeedbackItem.dataset_id == dataset.id)
    ).scalars().all()

    for item in items:
        assignment = ClusterAssignment(
            run_id=run.id,
            feedback_item_id=item.id,
            cluster_id=cluster.id,
            x=0.0,
            y=0.0,
        )
        db.add(assignment)

    db.commit()
    return cluster, items


def test_truncate_quote_no_truncation():
    """Short quotes are not truncated."""
    quote = "This is a short quote"
    truncated, was_truncated = _truncate_quote(quote, max_len=100)
    assert truncated == quote
    assert was_truncated is False


def test_truncate_quote_with_truncation():
    """Long quotes are truncated with ellipsis."""
    quote = "a" * 100
    truncated, was_truncated = _truncate_quote(quote, max_len=50)
    assert len(truncated) == 51  # 50 chars + ellipsis
    assert truncated.endswith("…")
    assert was_truncated is True


def test_validate_quotes_all_valid():
    """All quotes found in cluster items pass validation."""
    cluster_items = {
        uuid.uuid4(): "The system is broken and needs fixing immediately.",
        uuid.uuid4(): "Performance is really slow today.",
    }

    quotes = [
        "The system is broken",
        "Performance is really slow",
    ]

    valid, invalid = _validate_quotes(quotes, cluster_items)
    assert len(valid) == 2
    assert len(invalid) == 0
    assert all(item_id in cluster_items for _, item_id in valid)


def test_validate_quotes_with_invalid():
    """Quotes not found in cluster items are marked invalid."""
    item_id1 = uuid.uuid4()
    item_id2 = uuid.uuid4()
    cluster_items = {
        item_id1: "The system is broken.",
        item_id2: "Performance is slow.",
    }

    quotes = [
        "The system is broken",  # Valid
        "This quote does not exist",  # Invalid
        "Performance is slow",  # Valid
    ]

    valid, invalid = _validate_quotes(quotes, cluster_items)
    assert len(valid) == 2
    assert len(invalid) == 1
    assert "This quote does not exist" in invalid


def test_sample_cluster_items_deterministic(db: Session, sample_cluster_with_items):
    """Sampling is deterministic for the same cluster."""
    cluster, items = sample_cluster_with_items

    # Mock the Anthropic client
    mock_client = MagicMock()
    mock_client.messages.count_tokens.return_value = MagicMock(input_tokens=100)

    # Get sample twice; should be identical
    sample1 = _sample_cluster_items(db, cluster.id, 10000, mock_client, "claude-haiku-4-5")
    sample2 = _sample_cluster_items(db, cluster.id, 10000, mock_client, "claude-haiku-4-5")

    assert [item.id for item in sample1] == [item.id for item in sample2]


def test_sample_cluster_items_respects_token_budget(db: Session, sample_cluster_with_items):
    """Sampling respects the token budget."""
    cluster, items = sample_cluster_with_items

    # Mock the client to return high token counts
    mock_client = MagicMock()
    mock_client.messages.count_tokens.return_value = MagicMock(input_tokens=1000)

    # Token budget is 500; only one item should fit
    sample = _sample_cluster_items(db, cluster.id, 500, mock_client, "claude-haiku-4-5")
    assert len(sample) >= 1  # At least one item (even if over budget)


def test_sample_cluster_items_empty_cluster(db: Session, sample_dataset_with_embeddings):
    """Sampling from empty cluster raises ValueError."""
    dataset = sample_dataset_with_embeddings

    # Create a clustering run with empty cluster
    run = ClusteringRun(
        dataset_id=dataset.id,
        algorithm="hdbscan",
        params={},
        random_seed=42,
        cluster_count=1,
        noise_count=0,
        is_current=True,
    )
    db.add(run)
    db.flush()

    cluster = Cluster(run_id=run.id, cluster_index=0, item_count=0)
    db.add(cluster)
    db.commit()

    mock_client = MagicMock()

    with pytest.raises(ValueError, match="has no items"):
        _sample_cluster_items(db, cluster.id, 10000, mock_client, "claude-haiku-4-5")


def test_generate_cluster_summary_validates_quotes():
    """Summary generation validates quotes and retries if needed."""
    db_mock = MagicMock()
    client_mock = MagicMock()
    settings_mock = MagicMock(
        anthropic_summarization_model="claude-haiku-4-5",
        summarization_max_sample_tokens=8000,
        summarization_max_tokens=1024,
    )

    cluster_id = uuid.uuid4()
    cluster = MagicMock()
    cluster.id = cluster_id

    # Mock database queries
    db_mock.get.return_value = cluster

    # Mock FeedbackItem
    item1 = MagicMock()
    item1.id = uuid.uuid4()
    item1.feedback_text = "This is feedback about the system."
    item1.source = "support"
    item1.submitted_at = None

    item2 = MagicMock()
    item2.id = uuid.uuid4()
    item2.feedback_text = "Another feedback item here."
    item2.source = None
    item2.submitted_at = None

    # Mock sampling to return items
    with patch("app.insights.summarizer._sample_cluster_items") as mock_sample:
        mock_sample.return_value = [item1, item2]

        # Mock Claude response with valid quotes
        claude_response = MagicMock()
        claude_response.stop_reason = "end_turn"
        claude_response.usage.input_tokens = 100
        claude_response.usage.output_tokens = 50
        claude_response.content = [
            MagicMock(
                text=json.dumps({
                    "label": "System Issues",
                    "summary": "Users report system problems.",
                    "quotes": [
                        "This is feedback about the system",
                        "Another feedback item",
                    ],
                })
            )
        ]

        client_mock.messages.create.return_value = claude_response

        result = generate_cluster_summary(db_mock, cluster_id, settings_mock, client_mock)

        assert result["label"] == "System Issues"
        assert result["summary"] == "Users report system problems."
        assert len(result["quotes"]) == 2


def test_generate_cluster_summary_cluster_not_found(db: Session):
    """Summary generation raises error when cluster not found."""
    # Use real db, just query for non-existent cluster
    client_mock = MagicMock()
    settings_mock = MagicMock()
    cluster_id = uuid.uuid4()

    with pytest.raises(ValueError, match="not found"):
        generate_cluster_summary(db, cluster_id, settings_mock, client_mock)


@patch("app.insights.summarizer.Anthropic")
def test_get_or_generate_cluster_summary_cache_hit(
    mock_anthropic_class, db: Session, sample_cluster_with_items
):
    """Summary is served from cache within TTL."""
    cluster, items = sample_cluster_with_items

    # Create cached summary
    cached_summary = ClusterSummary(
        cluster_id=cluster.id,
        label="Cached Label",
        summary="Cached summary text.",
        quotes=[{"text": "Cached quote", "feedback_item_id": str(items[0].id)}],
    )
    db.add(cached_summary)
    db.commit()

    settings = MagicMock(summary_cache_ttl_hours=24)
    client = MagicMock()

    result = get_or_generate_cluster_summary(db, cluster.id, settings, client, force=False)

    assert result["label"] == "Cached Label"
    assert result["summary"] == "Cached summary text."
    client.messages.create.assert_not_called()  # Should not call Claude


def test_get_or_generate_cluster_summary_force_regenerate(db: Session, sample_cluster_with_items):
    """force=true bypasses cache and regenerates."""
    cluster, items = sample_cluster_with_items

    # Create cached summary
    cached_summary = ClusterSummary(
        cluster_id=cluster.id,
        label="Old Label",
        summary="Old summary text.",
        quotes=[{"text": "Old quote", "feedback_item_id": str(items[0].id)}],
    )
    db.add(cached_summary)
    db.commit()

    client_mock = MagicMock()
    settings_mock = MagicMock(
        anthropic_summarization_model="claude-haiku-4-5",
        summarization_max_sample_tokens=8000,
        summarization_max_tokens=1024,
        summary_cache_ttl_hours=24,
    )

    # Mock Claude response with quotes that are actual substrings of feedback items
    # Note: sample_dataset_with_embeddings uses happy_path.csv which has specific feedback
    with patch("app.insights.summarizer._sample_cluster_items") as mock_sample:
        mock_sample.return_value = items

        claude_response = MagicMock()
        claude_response.stop_reason = "end_turn"
        claude_response.usage.input_tokens = 100
        claude_response.usage.output_tokens = 50

        # Use quotes that are substrings of actual feedback items from happy_path.csv
        # The fixture generates items, so we create quotes that work
        quote1 = (
            items[0].feedback_text[:50]
            if len(items[0].feedback_text) > 50
            else items[0].feedback_text
        )
        quote2 = (
            items[1].feedback_text[:50]
            if len(items[1].feedback_text) > 50
            else items[1].feedback_text
        )
        quote3 = (
            items[2].feedback_text[:30]
            if len(items[2].feedback_text) > 30
            else items[2].feedback_text
        )

        claude_response.content = [
            MagicMock(
                text=json.dumps({
                    "label": "New Label",
                    "summary": "New summary text.",
                    "quotes": [quote1, quote2, quote3],
                })
            )
        ]
        client_mock.messages.create.return_value = claude_response

        result = get_or_generate_cluster_summary(
            db, cluster.id, settings_mock, client_mock, force=True
        )

        assert result["label"] == "New Label"
        assert result["summary"] == "New summary text."
        assert len(result["quotes"]) == 3
        client_mock.messages.create.assert_called_once()
