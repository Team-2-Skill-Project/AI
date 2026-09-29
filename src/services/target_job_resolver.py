"""Resolve persisted jobs and pasted descriptions into one internal target model."""

from __future__ import annotations

from src.db.repositories.job_repository import DatabaseJobRepository
from src.job_extractor.models import JobRequirementProfile
from src.job_extractor.pipeline import JobExtractionPipeline
from src.models.target_job import ResolvedTargetJob


class TargetJobNotFoundError(LookupError):
    """The supplied persisted job ID does not exist."""


class TargetJobExtractionError(RuntimeError):
    """A pasted job description could not be safely extracted."""


class TargetJobResolver:
    """Source-agnostic target resolution with no persistence side effect for pasted JDs."""

    def __init__(self, job_repository: DatabaseJobRepository, job_pipeline: JobExtractionPipeline) -> None:
        self._job_repository = job_repository
        self._job_pipeline = job_pipeline

    def resolve_by_job_id(self, job_id: str) -> ResolvedTargetJob:
        job = self._job_repository.get_job_by_id(job_id)
        if job is None:
            raise TargetJobNotFoundError(f"Job '{job_id}' was not found.")
        profile = self._job_repository.get_structured_profile_by_id(job_id)
        if profile is None:
            return ResolvedTargetJob.from_job_posting(job)
        return ResolvedTargetJob(
            target_source="persisted_job",
            job_id=job.job_id,
            title=job.title or None,
            company=job.company,
            source=job.source,
            source_url=job.source_url,
            posted_at=job.posted_at,
            expires_at=job.expires_at,
            source_updated_at=job.source_updated_at,
            ingested_at=job.ingested_at,
            canonical_role=profile.canonical_role or job.canonical_role,
            role_family=profile.role_family or job.role_family,
            seniority=profile.seniority or job.experience_level,
            required_skills=profile.required_skills,
            preferred_skills=profile.preferred_skills,
            responsibilities=profile.responsibilities,
            min_years_experience=(
                profile.min_years_experience
                if profile.min_years_experience is not None
                else job.min_years_experience
            ),
            max_years_experience=profile.max_years_experience,
            profile_reused=True,
        )

    def resolve_from_description(self, job_description: str) -> ResolvedTargetJob:
        try:
            profile = self._job_pipeline.extract(job_description)
        except Exception as exc:
            raise TargetJobExtractionError("Job description extraction failed.") from exc
        return self._from_extracted_profile(profile)

    @staticmethod
    def _from_extracted_profile(profile: JobRequirementProfile) -> ResolvedTargetJob:
        return ResolvedTargetJob(
            target_source="external_description",
            canonical_role=profile.canonical_role,
            role_family=profile.role_family,
            seniority=profile.seniority,
            required_skills=profile.required_skills,
            preferred_skills=profile.preferred_skills,
            responsibilities=profile.responsibilities,
            min_years_experience=profile.min_years_experience,
            max_years_experience=profile.max_years_experience,
        )
