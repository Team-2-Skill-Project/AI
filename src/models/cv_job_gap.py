"""Internal, evidence-first models for CV-to-job gap analysis.

These models are deliberately separate from public API schemas.  They preserve
the source facts that support an analysis and do not contain rewrite or LLM
suggestions.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvidenceReference(BaseModel):
    """A reference to an exact fact already present on the candidate."""

    source_type: str
    source_index: int | None = None
    source_field: str | None = None
    text: str


class SkillEvidence(BaseModel):
    """All known factual evidence for one candidate skill identity."""

    skill_id: str | None = None
    canonical_name: str
    category: str | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    strength: Literal["unknown", "listed", "contextual", "corroborated", "measured_context"] = "unknown"


class SkillGapItem(BaseModel):
    """One required or preferred job skill compared with the CV."""

    skill_id: str | None = None
    canonical_name: str
    category: str | None = None
    raw_requirement: str
    requirement_type: Literal["required", "preferred"]
    matched: bool
    candidate_proficiency: str | None = None
    evidence_strength: Literal["unknown", "listed", "contextual", "corroborated", "measured_context"] = "unknown"
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ExperienceAlignment(BaseModel):
    """Conservative calendar-duration comparison, never an inferred seniority."""

    minimum_years: float | None = None
    maximum_years: float | None = None
    known_years: float | None = None
    date_coverage: Literal["unavailable", "partial", "complete"] = "unavailable"
    status: Literal[
        "not_specified",
        "unknown",
        "below_minimum",
        "meets_minimum",
        "within_range",
        "above_maximum",
    ] = "not_specified"
    evidence: list[EvidenceReference] = Field(default_factory=list)


class RoleAlignment(BaseModel):
    """Exact structured-role comparison; unknown is preferred to semantic guessing."""

    target_role: str | None = None
    status: Literal["unknown", "aligned", "not_aligned"] = "unknown"
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ResponsibilityAlignment(BaseModel):
    """Deterministic exact responsibility evidence, without semantic inference."""

    responsibility: str
    status: Literal["supported", "unknown"] = "unknown"
    evidence: list[EvidenceReference] = Field(default_factory=list)


class CVJobGapResult(BaseModel):
    """Internal result returned by :class:`CVJobGapAnalyzer`."""

    candidate_id: str
    job_id: str | None = None
    required_skill_gaps: list[SkillGapItem] = Field(default_factory=list)
    preferred_skill_gaps: list[SkillGapItem] = Field(default_factory=list)
    extra_candidate_skills: list[SkillEvidence] = Field(default_factory=list)
    candidate_evidence: list[SkillEvidence] = Field(default_factory=list)
    experience_alignment: ExperienceAlignment = Field(default_factory=ExperienceAlignment)
    role_alignment: RoleAlignment = Field(default_factory=RoleAlignment)
    responsibility_alignment: list[ResponsibilityAlignment] = Field(default_factory=list)
