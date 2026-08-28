"""Liveness probe."""

import logging

from anthropic import Anthropic, APIError
from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return service liveness status."""
    return {"status": "ok"}


@router.get("/health/llm")
def llm_health() -> dict[str, str]:
    """Check Anthropic API connectivity and configuration.

    Makes a real API call to verify the key works and Claude responds.
    This is not a real summarization — just a test message.

    Returns:
        200 with {"status": "ok"} if the API key is set and Claude responds.
        503 if API key is missing or Claude is unreachable.
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        logger.warning("LLM health check: API key not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Anthropic API key not configured",
        )

    try:
        logger.info(f"LLM health check: testing {settings.anthropic_summarization_model}")
        client = Anthropic(api_key=settings.anthropic_api_key)
        # Make a real API call to verify key works
        response = client.messages.create(
            model=settings.anthropic_summarization_model,
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        inp_tokens = response.usage.input_tokens
        out_tokens = response.usage.output_tokens
        logger.info(f"LLM health check: OK ({inp_tokens}→{out_tokens} tokens)")
        return {
            "status": "ok",
            "model": settings.anthropic_summarization_model,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
    except APIError as exc:
        logger.error(f"LLM health check: API error: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Anthropic API error: {str(exc)}",
        ) from exc
    except Exception as exc:
        logger.error(f"LLM health check: Unexpected error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Unexpected error: {str(exc)}",
        ) from exc
