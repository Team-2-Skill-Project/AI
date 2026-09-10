from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.db.base import get_db
from src.db.repositories.match_repository import MatchRepository
from src.schemas.match import SkillGapAnalysisRequest, SkillGapAnalysisResponse
from src.services.matching_service import matching_service

router = APIRouter(prefix="/matches", tags=["Skill Gap Analysis & Explainable Match"])


# =========================================================================
# Feature 2: Automated Skill Gap Analysis
# =========================================================================

@router.post(
    "/analyze",
    response_model=SkillGapAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Perform automated skill gap analysis",
    description=(
        "Evaluates a candidate profile against structured job requirements. "
        "Calculates individual skill match scores (0-100), identifies missing critical skills, "
        "determines qualification status (Qualified, Partially Qualified, Not Qualified), "
        "and outlines a prioritized upskilling roadmap."
    ),
)
async def analyze_candidate_skill_gap(payload: SkillGapAnalysisRequest) -> SkillGapAnalysisResponse:
    return await matching_service.analyze_skill_gap(payload)


@router.post(
    "/skill-gap",
    response_model=SkillGapAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Dedicated Skill Gap Analysis Endpoint",
    description="Explicit endpoint for automated Skill Gap Analysis comparing candidate skills to job requirements."
)
async def evaluate_skill_gap(payload: SkillGapAnalysisRequest) -> SkillGapAnalysisResponse:
    return await matching_service.analyze_skill_gap(payload)


# =========================================================================
# Feature 3: Explainable Job Match
# =========================================================================

@router.post(
    "/explain",
    response_model=SkillGapAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate Explainable Job Match Insight",
    description=(
        "Compares a candidate profile against job requirements to produce an explainable match report. "
        "Includes executive natural-language reasoning ('why'), matched strengths with verbatim evidence snippets, "
        "and prioritized gap mitigation."
    )
)
async def explain_job_match(
    payload: SkillGapAnalysisRequest,
    db: Session = Depends(get_db)
) -> SkillGapAnalysisResponse:
    result = await matching_service.analyze_skill_gap(payload)
    # Persist match result to database for auditability and caching
    try:
        repo = MatchRepository(db)
        repo.save_match_result(result)
    except Exception:
        # Graceful fallback if database persistence encounters a transient error
        pass
    return result


@router.get(
    "/{job_id}/candidate/{candidate_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Retrieve Persisted Match Explanation",
    description="Fetches the latest stored explainable match evaluation between a specific job and candidate."
)
def get_persisted_match_explanation(
    job_id: str,
    candidate_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    repo = MatchRepository(db)
    record = repo.get_latest_match(job_id=job_id, candidate_id=candidate_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No match record found for job '{job_id}' and candidate '{candidate_id}'."
        )
    return record.to_dict()


@router.get(
    "/candidate/{candidate_id}",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="List Match Explanations for Candidate",
    description="Lists all stored explainable match records for a given candidate."
)
def list_candidate_matches(
    candidate_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    repo = MatchRepository(db)
    records = repo.list_by_candidate(candidate_id=candidate_id, skip=skip, limit=limit)
    return [r.to_dict() for r in records]
