"""FastAPI endpoint router for Personalized Job Recommendations.

Endpoint:
    GET /api/v1/recommendations/feed
"""

from datetime import datetime, timezone
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.security import require_service_api_key
from src.db.repositories.behavior_repository import DatabaseBehaviorRepository
from src.repositories.candidate_repository import candidate_repository
from src.schemas.cv import ExtractionErrorResponse
from src.schemas.recommendation import (
    RecommendationEventRequest,
    RecommendationEventResponse,
    RecommendationFeedResponse,
)
from src.services.recommendation_service import RecommendationService, recommendation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["Personalized Job Recommendations"])


@router.get(
    "/feed",
    response_model=RecommendationFeedResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Personalized Job Recommendation Feed",
    description=(
        "Returns an ordered list of recommended jobs for a candidate. "
        "Scores jobs deterministically using candidate skills, target role, preferences, "
        "match quality, freshness, and interaction history. Excludes applied/dismissed jobs "
        "and deduplicates identical postings."
    ),
    responses={
        404: {"description": "Candidate not found", "model": ExtractionErrorResponse},
    },
)
async def get_recommendation_feed(
    candidate_id: str = Query(..., min_length=1, description="Unique identifier of the candidate"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=50, description="Number of recommendations per page"),
    work_mode: Optional[str] = Query(None, description="Optional work mode filter override (remote, hybrid, onsite)"),
    location: Optional[str] = Query(None, description="Optional location filter substring"),
    min_score: float = Query(0.0, ge=0.0, le=100.0, description="Minimum recommendation score cutoff"),
    service: RecommendationService = Depends(lambda: recommendation_service),
) -> RecommendationFeedResponse:
    """Retrieves paginated personalized recommendation feed."""
    candidate = candidate_repository.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{candidate_id}' was not found.",
        )

    return await service.get_recommendation_feed(
        candidate=candidate,
        page=page,
        limit=limit,
        work_mode=work_mode,
        location=location,
        min_score=min_score,
    )


@router.post(
    "/events",
    response_model=RecommendationEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record Candidate Job Interaction Event",
    description=(
        "Internal service endpoint for recording a candidate interaction with a job "
        "(view, click, save, unsave, apply, dismiss, undismiss). The trusted caller must authenticate and "
        "authorize the acting candidate before forwarding this request. "
        "Validates that both the candidate and job exist in persistence, enforces consistent state transitions, "
        "and updates the candidate's interaction history used by recommendation scoring."
    ),
    responses={
        201: {"description": "Interaction recorded successfully", "model": RecommendationEventResponse},
        400: {"description": "Invalid or unsupported event type", "model": ExtractionErrorResponse},
        401: {"description": "Invalid or missing service API key", "model": ExtractionErrorResponse},
        404: {"description": "Candidate or Job not found", "model": ExtractionErrorResponse},
        422: {"description": "Validation error in request payload", "model": ExtractionErrorResponse},
        503: {"description": "Service API key is not configured", "model": ExtractionErrorResponse},
    },
)
async def record_recommendation_event(
    payload: RecommendationEventRequest,
    _: str = Depends(require_service_api_key),
    service: RecommendationService = Depends(lambda: recommendation_service),
) -> RecommendationEventResponse:
    """Records an interaction event between a candidate and a job."""
    # 1. Validate candidate exists
    candidate = candidate_repository.get_candidate(payload.candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate '{payload.candidate_id}' was not found.",
        )

    # 2. Validate job exists
    job = service.job_repo.get_job_by_id(payload.job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{payload.job_id}' was not found.",
        )

    # 3. Validate and normalize event type
    try:
        canonical_type = DatabaseBehaviorRepository.normalize_interaction_type(payload.event_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # 4. Record interaction in persistent repository
    try:
        event_record = service.behavior_repo.record_interaction(
            candidate_id=payload.candidate_id,
            job_id=payload.job_id,
            interaction_type=canonical_type,
            metadata=payload.metadata,
        )
    except LookupError as exc:
        # The repository re-checks persistence at the write boundary to avoid
        # recording an orphaned interaction during a concurrent deletion.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    recorded_at = getattr(event_record, "created_at", None) or datetime.now(timezone.utc)

    return RecommendationEventResponse(
        success=True,
        candidate_id=payload.candidate_id,
        job_id=payload.job_id,
        event_type=canonical_type,
        recorded_at=recorded_at,
        message=f"Interaction '{canonical_type}' recorded successfully.",
    )
