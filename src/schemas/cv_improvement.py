"""Dedicated public API contract for the CV Improvement Assistant."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CVImprovementRequest(BaseModel):
    candidate_id: str = Field(..., min_length=1)
    job_id: str | None = None
    job_description: str | None = None

    @field_validator("candidate_id", "job_id", "job_description", mode="before")
    @classmethod
    def strip_strings(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_exactly_one_target(self) -> "CVImprovementRequest":
        has_job_id = bool(self.job_id)
        has_description = bool(self.job_description)
        if has_job_id == has_description:
            raise ValueError("Provide exactly one of job_id or job_description.")
        if self.job_description is not None and len(self.job_description) < 50:
            raise ValueError("job_description must contain at least 50 characters.")
        return self


class EvidenceCitationResponse(BaseModel):
    source_type: str
    source_index: int | None = None
    source_field: str | None = None
    text: str


class TargetJobReferenceResponse(BaseModel):
    source: Literal["persisted_job", "external_description"]
    job_id: str | None = None
    title: str | None = None
    company: str | None = None
    provider: str | None = None
    source_url: str | None = None
    canonical_role: str | None = None
    role_family: str | None = None
    seniority: str | None = None


class GapSkillResponse(BaseModel):
    skill_id: str | None = None
    canonical_name: str
    category: str | None = None
    requirement_type: Literal["required", "preferred"]
    evidence_strength: str


class GroundedStrengthResponse(BaseModel):
    skill_id: str | None = None
    canonical_name: str
    evidence_strength: str
    evidence: list[EvidenceCitationResponse] = Field(default_factory=list)


class ExperienceAlignmentResponse(BaseModel):
    minimum_years: float | None = None
    maximum_years: float | None = None
    known_years: float | None = None
    date_coverage: str
    status: str


class RoleAlignmentResponse(BaseModel):
    target_role: str | None = None
    status: str


class ResponsibilityAlignmentResponse(BaseModel):
    responsibility: str
    status: str


class GapAnalysisResponse(BaseModel):
    experience_alignment: ExperienceAlignmentResponse
    role_alignment: RoleAlignmentResponse
    responsibility_alignment: list[ResponsibilityAlignmentResponse] = Field(default_factory=list)


class CVImprovementSuggestionResponse(BaseModel):
    suggestion_type: str
    priority: Literal["high", "medium", "low"]
    target_section: str
    evidence: list[EvidenceCitationResponse] = Field(default_factory=list)
    current_text: str | None = None
    suggested_text: str | None = None
    reason: str
    related_job_requirement: str | None = None
    grounding_status: Literal["grounded", "gap", "unknown"]


class CVImprovementAPIResponse(BaseModel):
    candidate_id: str
    target_job: TargetJobReferenceResponse
    gap_analysis: GapAnalysisResponse
    grounded_strengths: list[GroundedStrengthResponse] = Field(default_factory=list)
    missing_required_skills: list[GapSkillResponse] = Field(default_factory=list)
    missing_preferred_skills: list[GapSkillResponse] = Field(default_factory=list)
    improvement_suggestions: list[CVImprovementSuggestionResponse] = Field(default_factory=list)
    safe_rewrites: list[CVImprovementSuggestionResponse] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
