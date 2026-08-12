"""SQLAlchemy engine, session factory, and declarative base.

The engine reads ``DATABASE_URL`` from settings. SQLite is the single-file
database (created automatically on first run) — no external service to
provision, no Docker. Vector search is handled separately via an in-memory
HNSW index (``hnswlib``), not a DB extension. No models are defined yet; the
pipeline stages add them via their own specs and Alembic migrations.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
engine = create_engine(_settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
