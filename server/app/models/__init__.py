"""Pydantic schemas and SQLAlchemy ORM models.

``app.models.db`` holds the SQLAlchemy ORM models (subclassing
``app.core.db.Base``); ``app.models.schemas`` holds the Pydantic
request/response schemas, kept separate so the OpenAPI surface never leaks
ORM internals. Both are imported here so Alembic's autogenerate (see
``alembic/env.py``) sees the ORM metadata without callers needing to know
the submodule layout.
"""

from app.models import db, schemas

__all__ = ["db", "schemas"]
