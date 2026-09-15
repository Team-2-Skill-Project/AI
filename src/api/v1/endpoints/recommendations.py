"""FastAPI endpoint router for Personalized Job Recommendations.

Endpoint:
    GET /api/v1/recommendations/feed
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.repositories.candidate_repository import candidate_repository
from src.schemas.recommendation import RecommendationFeedResponse
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
)
async def get_recommendation_feed(
    candidate_id: str = Query("cand_001", description="Unique identifier of the candidate"),
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
