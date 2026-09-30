"""Single orchestration path for persisted and external CV improvement targets."""

from __future__ import annotations

from dataclasses import dataclass

from src.models.candidate import Candidate
from src.models.cv_improvement import CVImprovementResult
from src.models.cv_job_gap import CVJobGapResult
from src.models.target_job import ResolvedTargetJob
from src.repositories.candidate_repository import CandidateRepository
from src.services.cv_improvement_generator import CVImprovementGenerator
from src.services.cv_job_gap_analyzer import CVJobGapAnalyzer
from src.services.target_job_resolver import TargetJobResolver


class CandidateNotFoundError(LookupError):
    """The requested persisted candidate does not exist."""


@dataclass(frozen=True)
class CVImprovementFlowResult:
    candidate: Candidate
    target_job: ResolvedTargetJob
    gap_result: CVJobGapResult
    improvement_result: CVImprovementResult


class CVImprovementFlow:
    """Resolve either target source, then always use the same analyzer and generator."""

    def __init__(
        self,
        candidate_repository: CandidateRepository,
        target_job_resolver: TargetJobResolver,
        gap_analyzer: CVJobGapAnalyzer,
        improvement_generator: CVImprovementGenerator,
    ) -> None:
        self._candidate_repository = candidate_repository
        self._target_job_resolver = target_job_resolver
        self._gap_analyzer = gap_analyzer
        self._improvement_generator = improvement_generator

    async def analyze(
        self,
        candidate_id: str,
        *,
        job_id: str | None = None,
        job_description: str | None = None,
    ) -> CVImprovementFlowResult:
        candidate = self._candidate_repository.get_candidate(candidate_id)
        if candidate is None:
            raise CandidateNotFoundError(f"Candidate '{candidate_id}' was not found.")
        if job_id is not None:
            target_job = self._target_job_resolver.resolve_by_job_id(job_id)
        elif job_description is not None:
            target_job = self._target_job_resolver.resolve_from_description(job_description)
        else:
            raise ValueError("A target job is required.")

        gap_result = self._gap_analyzer.analyze(candidate, target_job)
        improvement_result = await self._improvement_generator.generate(candidate, target_job, gap_result)
        return CVImprovementFlowResult(candidate, target_job, gap_result, improvement_result)
