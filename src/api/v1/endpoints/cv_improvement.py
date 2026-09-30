"""Candidate-bound CV Improvement Assistant API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import (
    get_cv_improvement_generator,
    get_cv_job_gap_analyzer,
    get_database_candidate_repository,
    get_database_job_repository,
    get_job_pipeline,
)
from src.db.repositories.candidate_repository import DatabaseCandidateRepository
from src.db.repositories.job_repository import DatabaseJobRepository
from src.job_extractor.pipeline import JobExtractionPipeline
from src.models.cv_job_gap import EvidenceReference, SkillEvidence, SkillGapItem
from src.schemas.cv import ExtractionErrorResponse
from src.schemas.cv_improvement import (
    CVImprovementAPIResponse,
    CVImprovementRequest,
    CVImprovementSuggestionResponse,
    EvidenceCitationResponse,
    ExperienceAlignmentResponse,
    GapAnalysisResponse,
    GapSkillResponse,
    GroundedStrengthResponse,
    ResponsibilityAlignmentResponse,
    RoleAlignmentResponse,
    TargetJobReferenceResponse,
)
from src.services.cv_improvement_flow import CandidateNotFoundError, CVImprovementFlow
from src.services.cv_improvement_generator import CVImprovementGenerationError, CVImprovementGenerator
from src.services.cv_job_gap_analyzer import CVJobGapAnalyzer
from src.services.target_job_resolver import TargetJobExtractionError, TargetJobNotFoundError, TargetJobResolver

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cv-improvement", tags=["CV Improvement Assistant"])


def _citation(reference: EvidenceReference) -> EvidenceCitationResponse:
    return EvidenceCitationResponse(**reference.model_dump())


def _gap_skill(item: SkillGapItem) -> GapSkillResponse:
    return GapSkillResponse(
        skill_id=item.skill_id,
        canonical_name=item.canonical_name,
        category=item.category,
        requirement_type=item.requirement_type,
        evidence_strength=item.evidence_strength,
    )


def _strength(item: SkillEvidence) -> GroundedStrengthResponse:
    return GroundedStrengthResponse(
        skill_id=item.skill_id,
        canonical_name=item.canonical_name,
        evidence_strength=item.strength,
        evidence=[_citation(reference) for reference in item.evidence],
    )


def _suggestion(item) -> CVImprovementSuggestionResponse:
    return CVImprovementSuggestionResponse(
        suggestion_type=item.suggestion_type,
        priority=item.priority,
        target_section=item.target_section,
        evidence=[_citation(reference) for reference in item.source_evidence_refs],
        current_text=item.current_text,
        suggested_text=item.suggested_text,
        reason=item.reason,
        related_job_requirement=item.related_job_requirement,
        grounding_status=item.grounding_status,
    )


def _response_from_flow(result) -> CVImprovementAPIResponse:
    target = result.target_job
    gap = result.gap_result
    matched = {
        (item.skill_id, item.canonical_name)
        for item in [*gap.required_skill_gaps, *gap.preferred_skill_gaps]
        if item.matched
    }
    strengths = [
        _strength(item)
        for item in gap.candidate_evidence
        if (item.skill_id, item.canonical_name) in matched
    ]
    required_gaps = [_gap_skill(item) for item in gap.required_skill_gaps if not item.matched]
    preferred_gaps = [_gap_skill(item) for item in gap.preferred_skill_gaps if not item.matched]
    suggestions = [_suggestion(item) for item in result.improvement_result.suggestions]
    limitations = [
        "The AI service does not independently verify candidate ownership; upstream callers must authorize access.",
    ]
    if required_gaps:
        limitations.append("Some required job requirements are not evidenced in the persisted candidate CV.")
    if target.target_source == "external_description":
        limitations.append("The pasted job description was analyzed ephemerally and was not persisted.")
    return CVImprovementAPIResponse(
        candidate_id=result.candidate.candidate_id,
        target_job=TargetJobReferenceResponse(
            source=target.target_source,
            job_id=target.job_id,
            title=target.title,
            company=target.company,
            provider=target.source,
            source_url=target.source_url,
            canonical_role=target.canonical_role,
            role_family=target.role_family,
            seniority=target.seniority,
        ),
        gap_analysis=GapAnalysisResponse(
            experience_alignment=ExperienceAlignmentResponse(
                minimum_years=gap.experience_alignment.minimum_years,
                maximum_years=gap.experience_alignment.maximum_years,
                known_years=gap.experience_alignment.known_years,
                date_coverage=gap.experience_alignment.date_coverage,
                status=gap.experience_alignment.status,
            ),
            role_alignment=RoleAlignmentResponse(
                target_role=gap.role_alignment.target_role,
                status=gap.role_alignment.status,
            ),
            responsibility_alignment=[
                ResponsibilityAlignmentResponse(
                    responsibility=item.responsibility,
                    status=item.status,
                )
                for item in gap.responsibility_alignment
            ],
        ),
        grounded_strengths=strengths,
        missing_required_skills=required_gaps,
        missing_preferred_skills=preferred_gaps,
        improvement_suggestions=suggestions,
        safe_rewrites=[item for item in suggestions if item.suggested_text is not None],
        limitations=limitations,
    )


@router.post(
    "/analyze",
    response_model=CVImprovementAPIResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze a persisted candidate CV against a target job",
    description=(
        "Requires a persisted candidate and exactly one target: a persisted job_id or an external job description. "
        "This service uses existing service-to-service API-key policy when enabled; it does not establish end-user ownership."
    ),
    responses={
        404: {"model": ExtractionErrorResponse, "description": "Candidate or persisted job not found"},
        400: {"model": ExtractionErrorResponse, "description": "Job extraction or improvement generation failed"},
        422: {"model": ExtractionErrorResponse, "description": "Invalid target-job request"},
    },
)
async def analyze_cv_improvement(
    payload: CVImprovementRequest,
    candidate_repository: DatabaseCandidateRepository = Depends(get_database_candidate_repository),
    job_repository: DatabaseJobRepository = Depends(get_database_job_repository),
    job_pipeline: JobExtractionPipeline = Depends(get_job_pipeline),
    gap_analyzer: CVJobGapAnalyzer = Depends(get_cv_job_gap_analyzer),
    improvement_generator: CVImprovementGenerator = Depends(get_cv_improvement_generator),
) -> CVImprovementAPIResponse:
    flow = CVImprovementFlow(
        candidate_repository,
        TargetJobResolver(job_repository, job_pipeline),
        gap_analyzer,
        improvement_generator,
    )
    try:
        result = await flow.analyze(
            payload.candidate_id,
            job_id=payload.job_id,
            job_description=payload.job_description,
        )
    except CandidateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": str(exc), "error_code": "CANDIDATE_NOT_FOUND"},
        ) from exc
    except TargetJobNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": str(exc), "error_code": "JOB_NOT_FOUND"},
        ) from exc
    except TargetJobExtractionError as exc:
        logger.warning("CV improvement target extraction failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": str(exc), "error_code": "JOB_EXTRACTION_FAILED"},
        ) from exc
    except CVImprovementGenerationError as exc:
        logger.warning("CV improvement generation failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "CV improvement generation failed.", "error_code": "CV_IMPROVEMENT_FAILED"},
        ) from exc
    return _response_from_flow(result)
