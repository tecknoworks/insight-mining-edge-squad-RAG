"""SQLAlchemy engine, session factory, and declarative base.

The engine reads ``DATABASE_URL`` from settings. Postgres (with the pgvector
extension) is expected to be provided by the developer locally — the app never
manages the database lifecycle. No models are defined yet; the pipeline stages
add them via their own specs and Alembic migrations.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
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
