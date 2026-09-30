"""Internal normalized target-job representation for CV improvement flows."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.job_extractor.models import NormalizedSkill
from src.schemas.job import JobPosting, SkillRequirement


class ResolvedTargetJob(BaseModel):
    """A persisted or ephemeral target represented with the same requirement fields."""

    target_source: Literal["persisted_job", "external_description"]
    job_id: str | None = None
    title: str | None = None
    company: str | None = None
    source: str | None = None
    source_url: str | None = None
    posted_at: datetime | str | None = None
    expires_at: datetime | str | None = None
    source_updated_at: datetime | str | None = None
    ingested_at: datetime | str | None = None
    canonical_role: str | None = None
    role_family: str | None = None
    seniority: str | None = None
    required_skills: list[NormalizedSkill | SkillRequirement] = Field(default_factory=list)
    preferred_skills: list[NormalizedSkill | SkillRequirement] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    min_years_experience: float | None = None
    max_years_experience: float | None = None
    profile_reused: bool = False

    @classmethod
    def from_job_posting(cls, job: JobPosting) -> "ResolvedTargetJob":
        """Keep an existing job usable even when it predates structured profiles."""
        return cls(
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
            canonical_role=job.canonical_role,
            role_family=job.role_family,
            seniority=job.experience_level,
            required_skills=job.required_skills,
            min_years_experience=job.min_years_experience,
        )
