"""Application settings.

All configuration is read from the environment (see ``server/.env.example``).
The two Anthropic model IDs are **system configuration**, not application logic —
every Claude call must read its model from ``summarization_model`` /
``chat_model``, never a hardcoded string. Changing a model means editing the env
var and redeploying (no runtime switching, no UI dropdown).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Anthropic / Claude ---
    anthropic_api_key: str = ""
    # Batch cluster summarization — cheapest tier is sufficient (high volume).
    anthropic_summarization_model: str = "claude-haiku-4-5"
    # Chat-with-data (RAG) — interactive, needs stronger reasoning.
    anthropic_chat_model: str = "claude-sonnet-5"

    # --- Embeddings (Voyage AI — Anthropic-recommended hosted provider) ---
    voyage_api_key: str = ""

    # --- Database ---
    database_url: str = "sqlite:///./insight_miner.db"

    # --- HTTP / CORS ---
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (read once per process)."""
    return Settings()
