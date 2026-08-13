"""Application settings.

All configuration is read from the environment (see ``server/.env.example``).
The two Anthropic model IDs are **system configuration**, not application logic —
every Claude call must read its model from ``summarization_model`` /
``chat_model``, never a hardcoded string. Changing a model means editing the env
var and redeploying (no runtime switching, no UI dropdown).
"""

import re
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The ``server/`` package directory, regardless of the process's current
# working directory. `pnpm dev` starts uvicorn with `--app-dir server` from
# the *repo root* (it does not `cd`), while manual `uv run`/`alembic` commands
# run with cwd=`server/` — two different cwds for the same app. Anchoring
# here, instead of leaving `.env` lookup and relative SQLite paths cwd-
# relative, keeps both invocations pointed at the same `.env` file and the
# same database file.
_SERVER_DIR = Path(__file__).resolve().parent.parent.parent

# Matches a relative `sqlite:///<path>` URL (3 slashes, not followed by a 4th
# — that's the absolute-path form — and not the special `:memory:` target).
_SQLITE_RELATIVE_PATH = re.compile(r"^sqlite:///(?!/)(?!:memory:)(.+)$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_SERVER_DIR / ".env",
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

    # --- Ingestion (CSV upload batching & error reporting) ---
    internal_batch_size: int = 1000
    max_reported_errors: int = 100

    @field_validator("database_url")
    @classmethod
    def _anchor_relative_sqlite_path(cls, value: str) -> str:
        """Resolve a relative ``sqlite:///`` path against ``server/``, not cwd."""
        match = _SQLITE_RELATIVE_PATH.match(value)
        if match is None:
            return value  # absolute sqlite path, :memory:, or a non-sqlite URL
        absolute_path = (_SERVER_DIR / match.group(1)).resolve()
        return f"sqlite:///{absolute_path}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance (read once per process)."""
    return Settings()
