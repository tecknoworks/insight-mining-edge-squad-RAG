"""CSV ingestion routes (placeholder).

Endpoints for uploading and validating feedback CSVs land here. Parsing/
validation logic belongs in ``app.ingestion``, not in these handlers.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/ingestion", tags=["ingestion"])
