from __future__ import annotations
"""Pydantic v2 output schemas for the Job Description Understanding feature."""

from typing import Literal

from pydantic import BaseModel, Field


class RawSkillItem(BaseModel):
    """Raw skill token extracted verbatim by the LLM from the job description."""

    name: str = Field(..., description="Skill name as it appears in the JD")
    importance: Literal["critical", "important", "nice_to_have"] = Field(
        "important",
        description=(
            "Importance level inferred from JD keywords: "
            "'must have'/'required' → critical; "
            "'preferred'/'nice to have' → nice_to_have; "
            "default → important"
        ),
    )
    required_level: Literal["beginner", "intermediate", "advanced", "expert"] | None = Field(
        None,
        description="Minimum proficiency level if explicitly mentioned in the JD",
    )


class NormalizedSkill(BaseModel):
    """A skill extracted from the JD, resolved against the platform taxonomy."""

    skill_id: str | None = Field(
        None,
        description="Canonical skill_id from TaxonomyManager; None if not found",
    )
    canonical_name: str = Field(..., description="Canonical display name")
    category: str | None = Field(None, description="Taxonomy category (e.g. 'Frameworks')")
    raw_extracted: str = Field(..., description="Verbatim skill token from the JD")
    importance: Literal["critical", "important", "nice_to_have"]
    required_level: Literal["beginner", "intermediate", "advanced", "expert"] | None = None


class JobRequirementProfile(BaseModel):
    """
    Structured requirement profile extracted from a raw job description.

    Zero-fabrication contract:
      - `role_family` and `seniority` are null when not determinable from the text.
      - No skill is fabricated; only tokens present in the JD are included.
    """

    role_family: str | None = Field(
        None,
        description="High-level role family (e.g. 'Engineering', 'Data'). "
                    "NULL if not determinable from the JD text.",
    )
    seniority: str | None = Field(
        None,
        description="Seniority level (e.g. 'Senior', 'Junior', 'Lead'). "
                    "NULL if not explicitly stated in the JD.",
    )
    canonical_role: str | None = Field(
        None,
        description="Normalized role title mapped to taxonomy (e.g. 'Data Scientist'). "
                    "NULL if not determinable.",
    )
    required_skills: list[NormalizedSkill] = Field(
        default_factory=list,
        description="Skills explicitly marked as required or must-have in the JD",
    )
    preferred_skills: list[NormalizedSkill] = Field(
        default_factory=list,
        description="Skills marked as preferred, nice-to-have, or bonus",
    )
    responsibilities: list[str] = Field(
        default_factory=list,
        description="Structured list of key responsibilities from the JD",
    )
    min_years_experience: int | None = Field(
        None,
        description="Lower bound of required experience in years",
    )
    max_years_experience: int | None = Field(
        None,
        description="Upper bound of required experience in years (None = open-ended)",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Non-skill requirements: location, work authorization, "
            "security clearance, domain certifications, etc."
        ),
    )
    extraction_confidence: float = Field(
        0.75,
        ge=0.0,
        le=1.0,
        description="Heuristic confidence score for the overall extraction quality",
    )
