"""CSV ingestion routes: upload, list, and detail.

Thin handlers only — parsing, validation, and persistence live in
``app.ingestion``.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.embeddings.client import EmbeddingClient, get_embedding_client
from app.embeddings.service import (
    DatasetNotFoundError,
    JobAlreadyRunningError,
    run_job,
    start_or_resume_job,
)
from app.ingestion.service import HeaderValidationError, ingest_csv
from app.models.db import Dataset, EmbeddingJob
from app.models.schemas import DatasetDetail, DatasetSummary, EmbeddingJobStatus, IngestionReport

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/uploads", response_model=IngestionReport, status_code=status.HTTP_201_CREATED)
def upload_csv(file: UploadFile, db: Session = Depends(get_db)) -> IngestionReport | JSONResponse:
    """Parse and persist an uploaded feedback CSV.

    Returns 201 with the ingestion report on success (even a partial one).
    Returns 400 — persisting nothing — when the header lacks
    ``feedback_text`` or when every data row was rejected.
    """
    try:
        report = ingest_csv(db, filename=file.filename or "upload.csv", raw_stream=file.file)
    except HeaderValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if report.rows_accepted == 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content=report.model_dump(mode="json")
        )

    return report


@router.get("/datasets", response_model=list[DatasetSummary])
def list_datasets(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[Dataset]:
    """List datasets newest-first, paginated."""
    return list(
        db.execute(
            select(Dataset).order_by(Dataset.created_at.desc()).limit(limit).offset(offset)
        ).scalars()
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: uuid.UUID, db: Session = Depends(get_db)) -> Dataset:
    """Fetch one dataset and every feedback item ingested from it."""
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")
    return dataset


@router.post(
    "/datasets/{dataset_id}/embed",
    response_model=EmbeddingJobStatus,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_embedding_job(
    dataset_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
) -> EmbeddingJob:
    """Start or resume embedding every un-embedded feedback item in a dataset."""
    try:
        job = start_or_resume_job(db, dataset_id)
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except JobAlreadyRunningError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if job.items_total > 0:
        background_tasks.add_task(run_job, dataset_id, embedding_client)
    return job


@router.get("/datasets/{dataset_id}/embed", response_model=EmbeddingJobStatus)
def get_embedding_job(dataset_id: uuid.UUID, db: Session = Depends(get_db)) -> EmbeddingJob:
    """Fetch the latest embedding job's status for a dataset."""
    job = db.execute(
        select(EmbeddingJob).where(EmbeddingJob.dataset_id == dataset_id)
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no embedding job found for this dataset",
        )
    return job
