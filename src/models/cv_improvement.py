"""Internal evidence-grounded CV improvement result models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from src.models.cv_job_gap import EvidenceReference

SuggestionType = Literal[
    "summary",
    "headline",
    "skills_presentation",
    "experience_bullet",
    "project_framing",
    "missing_requirement",
    "weak_evidence",
    "keyword_opportunity",
    "section_evidence",
    "responsibility_alignment",
    "general",
]

RewriteOpportunityType = Literal[
    "surface_supported_requirement",
    "clarify_existing_experience",
    "clarify_existing_project",
    "surface_existing_metric",
    "strengthen_target_relevance",
]


class CVImprovementSuggestion(BaseModel):
    """One internal, source-grounded presentation or gap suggestion."""

    suggestion_type: SuggestionType
    priority: Literal["high", "medium", "low"] = "low"
    target_section: str
    source_evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    current_text: str | None = None
    suggested_text: str | None = None
    reason: str
    related_job_requirement: str | None = None
    grounding_status: Literal["grounded", "gap", "unknown"] = "unknown"


class EvidenceCatalogItem(BaseModel):
    """One opaque, exact candidate-evidence item allowed to the LLM."""

    evidence_id: str
    source_section: str
    source_index: int | None = None
    source_field: str | None = None
    text: str
    supported_skills: list[str] = Field(default_factory=list)


class TargetReferenceCatalogItem(BaseModel):
    """One opaque current-job reference allowed to the LLM."""

    reference_id: str
    reference_type: Literal["required_skill", "preferred_skill", "responsibility"]
    text: str
    canonical_name: str | None = None
    matched: bool | None = None


class RewriteOpportunity(BaseModel):
    """A deterministic, local-evidence-bounded candidate rewrite opportunity."""

    opportunity_id: str
    evidence_id: str
    source_section: str
    source_index: int | None = None
    current_text: str
    target_requirement_ids: list[str] = Field(default_factory=list)
    responsibility_ids: list[str] = Field(default_factory=list)
    evidence_strength: Literal["unknown", "listed", "contextual", "corroborated", "measured_context"]
    opportunity_type: RewriteOpportunityType
    priority: Literal["high", "medium", "low"]
    reason: str
    allowed_supported_concepts: list[str] = Field(default_factory=list)
    allowed_fact_texts: list[str] = Field(default_factory=list)
    allowed_metrics: list[str] = Field(default_factory=list)


class LLMImprovementSuggestion(BaseModel):
    """Untrusted catalog-ID-based draft returned by the LLM.

    Legacy source fields remain optional solely so existing internal callers can
    be migrated without changing the public API contract. Runtime generation is
    instructed to use only ``evidence_ids`` and ``target_requirement_ids``.
    """

    suggestion_type: SuggestionType
    priority: Literal["high", "medium", "low"] = "low"
    target_section: str
    opportunity_id: str | None = Field(default=None, description="ID of one supplied rewrite opportunity.")
    evidence_ids: list[str] = Field(default_factory=list, description="Non-empty list of allowed E-prefixed evidence IDs.")
    target_requirement_ids: list[str] = Field(
        default_factory=list, description="Allowed R, P, or RESP target-reference IDs when applicable."
    )
    current_text: str | None = Field(default=None, description="Exact text copied from one cited evidence item.")
    suggested_text: str | None = Field(default=None, description="Non-empty factual rewrite of cited evidence.")
    reason: str
    grounding_status: Literal["grounded", "gap", "unknown"] = "unknown"
    source_evidence_refs: SkipJsonSchema[list[EvidenceReference]] = Field(default_factory=list, exclude=True)
    related_job_requirement: SkipJsonSchema[str | None] = Field(default=None, exclude=True)


class LLMImprovementDraft(BaseModel):
    """Untrusted structured draft returned by the centralized LLM."""

    suggestions: list[LLMImprovementSuggestion] = Field(default_factory=list)

    @field_validator("suggestions", mode="before")
    @classmethod
    def accept_legacy_internal_suggestions(cls, value):
        """Permit existing internal test doubles during the catalog-ID migration."""
        if not isinstance(value, list):
            return value
        return [item.model_dump() if isinstance(item, CVImprovementSuggestion) else item for item in value]


class CVImprovementResult(BaseModel):
    """Validated internal output of the CV Improvement Assistant."""

    candidate_id: str
    job_id: str | None = None
    suggestions: list[CVImprovementSuggestion] = Field(default_factory=list)
    rejected_suggestion_count: int = 0
    raw_draft_count: int = 0
    initial_accepted_count: int = 0
    repair_attempt_count: int = 0
    repaired_accepted_count: int = 0
    rejected_for_fabrication_count: int = 0
    rejected_for_low_value_count: int = 0
