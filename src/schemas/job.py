from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Union
from pydantic import BaseModel, Field

from src.job_extractor.models import JobRequirementProfile


class SkillRequirement(BaseModel):
    skill_id: Optional[str] = Field(default=None, description="Stable Skill Registry identity when resolved")
    skill_name: str = Field(description="Name of the required skill or tool")
    proficiency: str = Field(default="Intermediate", description="Expected proficiency level (e.g., Basic, Intermediate, Advanced, Expert)")
    is_critical: bool = Field(default=False, description="Whether this skill is a non-negotiable core requirement")
    category: Optional[str] = Field(default=None, description="Category such as Programming Languages, Frameworks, Databases, Cloud")
    min_years_experience: Optional[float] = Field(default=None, description="Minimum years of practical experience expected")
    description: Optional[str] = Field(default=None, description="Contextual note on how this skill is applied in the role")

    @classmethod
    def from_any(cls, item: Union[str, dict, "SkillRequirement"]) -> "SkillRequirement":
        if isinstance(item, cls):
            return item
        if isinstance(item, str):
            return cls(skill_name=item)
        if isinstance(item, dict):
            name = item.get("skill_name") or item.get("name") or "Unknown"
            return cls(
                skill_id=item.get("skill_id"),
                skill_name=name,
                proficiency=item.get("proficiency") or item.get("expected_proficiency") or "Intermediate",
                is_critical=bool(item.get("is_critical", False)),
                category=item.get("category"),
                min_years_experience=item.get("min_years_experience"),
                description=item.get("description"),
            )
        return cls(skill_name=str(item))


class JobPosting(BaseModel):
    job_id: str = Field(description="Unique identifier for the job position")
    title: str = Field(default="", description="Job title / role designation")
    company: Optional[str] = Field(default=None, description="Hiring organization / company name")
    role: Optional[str] = Field(default=None, description="Raw role or title designation")
    canonical_role: Optional[str] = Field(default=None, description="Taxonomy normalized role title")
    role_family: Optional[str] = Field(default=None, description="High-level role family (e.g. Engineering, Data & AI)")
    description: Optional[str] = Field(default=None, description="Full job description")
    department: Optional[str] = Field(default=None, description="Department or business team")
    location: Optional[str] = Field(default=None, description="Work location / city")
    work_mode: Optional[str] = Field(default="remote", description="remote, hybrid, or onsite")
    employment_type: Optional[str] = Field(default="full_time", description="full_time, part_time, contract, internship")
    experience_level: Optional[str] = Field(default=None, description="Entry, Mid, Senior, Lead")
    min_years_experience: Optional[float] = Field(default=None, description="Minimum total years of professional experience")
    posted_at: Optional[Union[datetime, str]] = Field(default=None, description="Posting creation timestamp")
    expires_at: Optional[Union[datetime, str]] = Field(default=None, description="Posting expiration timestamp")
    is_active: bool = Field(default=True, description="Whether the job posting is active")
    source_url: Optional[str] = Field(default=None, description="Original source listing URL")
    salary: Optional[str] = Field(default=None, description="Raw salary text when supplied by the source")
    source: Optional[str] = Field(default=None, description="Source provider attribution")
    source_external_id: Optional[str] = Field(default=None, description="Identifier assigned by the source provider")
    source_updated_at: Optional[Union[datetime, str]] = Field(default=None, description="Source update timestamp")
    ingested_at: Optional[Union[datetime, str]] = Field(default=None, description="Timestamp when the source record was ingested")
    description_is_partial: bool = Field(default=False, description="Whether description is only a source snippet")
    required_skills: List[SkillRequirement] = Field(default=[], description="List of required technical and domain skills")


class JobRequirementsPayload(BaseModel):
    job_id: Optional[str] = Field(default=None, description="Optional job ID")
    role_title: Optional[str] = Field(default=None, description="Title of the target role")
    skills: List[SkillRequirement] = Field(default=[], description="List of required skills and competencies")
    summary: Optional[str] = Field(default=None, description="High level summary of the job requirements")


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
