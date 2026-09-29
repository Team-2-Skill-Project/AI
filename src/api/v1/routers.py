"""Aggregated API v1 Router for all SkillMatch features."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.security import check_rate_limit
from src.api.v1.endpoints.cv import router as cv_router
from src.api.v1.endpoints.cv_improvement import router as cv_improvement_router
from src.api.v1.endpoints.interview import router as interview_router
from src.api.v1.endpoints.jobs import router as jobs_router
from src.api.v1.endpoints.matches import router as matches_router
from src.api.v1.endpoints.recommendations import router as recommendations_router
from src.api.v1.endpoints.review_queue import router as review_queue_router
from src.api.v1.endpoints.roadmap import router as roadmap_router

api_router = APIRouter()

# CV extraction retains its route-level rate limiter dependency to adhere to
# the ExtractionErrorResponse error contract while being exempt from the middleware.
api_router.include_router(cv_router, dependencies=[Depends(check_rate_limit)])
api_router.include_router(cv_improvement_router)

api_router.include_router(jobs_router)
api_router.include_router(matches_router)
api_router.include_router(review_queue_router)
api_router.include_router(roadmap_router)
api_router.include_router(recommendations_router)
api_router.include_router(interview_router)

# Compatibility alias
router = api_router

__all__ = ["api_router", "router"]
