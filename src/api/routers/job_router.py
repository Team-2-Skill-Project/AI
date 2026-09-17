from __future__ import annotations
"""
FastAPI router for the Job Description Understanding feature.

Endpoint:
    POST /api/v1/jobs/analyze

Auth:
    verify_api_key dependency (inherited from main.py registration).

Rate Limit:
    Global RateLimitMiddleware (applied at app level).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import get_job_pipeline
from src.api.schemas.cv_schemas import ExtractionErrorResponse
from src.api.schemas.job_schemas import JobAnalysisRequest, JobAnalysisResponse
from src.db.repositories.job_requirement_repository import JobRequirementRepository
from src.job_extractor.pipeline import JobExtractionPipeline

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/jobs",
    tags=["Job Description Understanding"],
)


@router.post(
    "/analyze",
    response_model=JobAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze a Job Description",
    description=(
        "Transform a raw job description into a structured requirement profile: "
        "role family, seniority, required/preferred skills (normalized to the platform taxonomy), "
        "responsibilities, experience expectations, and constraints.\n\n"
        "**Zero-fabrication contract:** `role_family` and `seniority` are `null` when "
        "they cannot be determined from the text. No skills are invented."
    ),
    responses={
        400: {"model": ExtractionErrorResponse, "description": "Extraction failed"},
        422: {"model": ExtractionErrorResponse, "description": "Validation error"},
        500: {"model": ExtractionErrorResponse, "description": "Internal server error"},
    },
)
async def analyze_job_description(
    payload: JobAnalysisRequest,
    pipeline: JobExtractionPipeline = Depends(get_job_pipeline),
) -> JobAnalysisResponse:
    """Extract a structured requirement profile from a raw job description."""
    # ── Step 1: Run extraction pipeline ────────────────────────────────
    try:
        profile = pipeline.extract(payload.job_description)
    except ValueError as ve:
        logger.warning("Job description extraction failed: %s", ve)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": str(ve), "error_code": "JOB_EXTRACTION_FAILED"},
        )
    except Exception as e:
        logger.error("Unexpected error during job extraction: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": "An unexpected error occurred.", "error_code": "INTERNAL_SERVER_ERROR"},
        )

    # ── Step 2: Optionally persist to DB ───────────────────────────────
    persisted = False
    if payload.job_id:
        try:
            repo = JobRequirementRepository()
            persisted = repo.upsert(job_id=payload.job_id, profile=profile)
        except Exception as db_err:
            # DB persistence failure is non-fatal — log and continue
            logger.warning(
                "DB upsert failed for job_id=%s (non-fatal): %s",
                payload.job_id,
                db_err,
            )

    return JobAnalysisResponse(
        job_id=payload.job_id,
        profile=profile,
        persisted=persisted,
    )
