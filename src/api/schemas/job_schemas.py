from __future__ import annotations
"""FastAPI request/response schemas for the Job Description Understanding endpoint."""

from pydantic import BaseModel, Field

from src.job_extractor.models import JobRequirementProfile


class JobAnalysisRequest(BaseModel):
    """Request payload for POST /api/v1/jobs/analyze."""

    job_description: str = Field(
        ...,
        min_length=50,
        max_length=20_000,
        description="Raw text of the job posting to analyze",
        json_schema_extra={
            "example": (
                "We are looking for a Senior Backend Engineer with 5+ years of experience "
                "in Python and FastAPI. Strong knowledge of PostgreSQL and Redis is required. "
                "Experience with Docker and Kubernetes is a plus."
            )
        },
    )
    job_id: str | None = Field(
        None,
        description=(
            "Optional UUID of an existing job record. "
            "When provided, the extracted profile is upserted into the jobs table."
        ),
        json_schema_extra={"example": "550e8400-e29b-41d4-a716-446655440000"},
    )


class JobAnalysisResponse(BaseModel):
    """Response payload for POST /api/v1/jobs/analyze."""

    job_id: str | None = Field(
        None,
        description="Echo of the job_id supplied in the request, or null if none was provided",
    )
    profile: JobRequirementProfile = Field(
        ...,
        description="Structured job requirement profile extracted from the job description",
    )
    persisted: bool = Field(
        ...,
        description=(
            "True if the profile was successfully upserted into the jobs table. "
            "False when job_id was not provided or the record was not found in DB."
        ),
    )
