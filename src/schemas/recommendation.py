"""Pydantic v2 schemas for Personalized Job Recommendations.

Fully compatible with the shared DAY 1 Contract:
Root response contains `candidate_id` and `recommendations` list where each
item contains `job_id`, `rank`, `score`, and `reasons: List[str]`, along with
rich structured breakdown and explanation metadata.
"""

from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class RecommendationReason(BaseModel):
    """Structured evidence-based reason for recommending a job."""
    code: str = Field(description="Machine-readable reason code, e.g. SKILL_MATCH_HIGH, TARGET_ROLE_MATCH")
    category: Literal["skills", "role", "experience", "preference", "freshness", "behavior"] = Field(
        description="Category of the recommendation signal"
    )
    text: str = Field(description="Human-readable explanation text")
    weight: Literal["primary", "secondary", "supporting"] = Field(
        default="supporting",
        description="Importance weight of this specific reason"
    )


class RecommendationExplanation(BaseModel):
    """Factual explanation containing structured reasons and concrete matched/missing skills."""
    headline: str = Field(description="Concise summary headline of why this job is recommended")
    reasons: List[RecommendationReason] = Field(default_factory=list, description="Structured factual reasons")
    matched_skills: List[str] = Field(default_factory=list, description="Names of candidate skills matching job requirements")
    missing_skills: List[str] = Field(default_factory=list, description="Names of required job skills missing from candidate profile")


class ScoreBreakdown(BaseModel):
    """Normalized sub-scores (0.0 - 100.0) contributing to the final recommendation score."""
    match_score: float = Field(ge=0.0, le=100.0, description="Core technical qualification score from MatchingService (0-100)")
    role_relevance_score: float = Field(ge=0.0, le=100.0, description="Target role alignment score (0-100)")
    preference_fit_score: float = Field(ge=0.0, le=100.0, description="Work mode, location, and employment type fit (0-100)")
    freshness_score: float = Field(ge=0.0, le=100.0, description="Exponential decay recency score (0-100)")
    behavior_boost: float = Field(default=50.0, ge=0.0, le=100.0, description="Interaction affinity score (0-100, neutral=50.0)")


class RecommendedJobItem(BaseModel):
    """Individual recommended job entry in the feed."""
    # --- Strict DAY 1 Shared Contract Fields ---
    job_id: str = Field(description="Unique job identifier")
    rank: int = Field(ge=1, description="1-indexed rank position in the feed")
    score: float = Field(ge=0.0, le=100.0, description="Composite deterministic recommendation score (0-100)")
    reasons: List[str] = Field(default_factory=list, description="Concise string list of recommendation reasons (DAY 1 compatible)")

    # --- Rich Metadata & Structured Breakdown ---
    title: str = Field(default="", description="Job title")
    company: Optional[str] = Field(default=None, description="Hiring company name")
    location: Optional[str] = Field(default=None, description="Geographic location / city")
    work_mode: Optional[str] = Field(default=None, description="remote, hybrid, or onsite")
    employment_type: Optional[str] = Field(default=None, description="full_time, part_time, contract, internship")
    experience_level: Optional[str] = Field(default=None, description="Entry, Mid, Senior, Lead")
    posted_at: Optional[datetime] = Field(default=None, description="Timestamp when the job was posted")
    qualification_status: str = Field(default="Qualified", description="Verdict from MatchingService: Qualified, Partially Qualified, Not Qualified")
    score_breakdown: ScoreBreakdown = Field(description="Granular component scores")
    explanation: RecommendationExplanation = Field(description="Evidence-based explanation breakdown")
    is_saved: bool = Field(default=False, description="Whether the candidate previously saved this job")
    is_applied: bool = Field(default=False, description="Whether the candidate has applied to this job")


class RecommendationFeedResponse(BaseModel):
    """Top-level recommendation feed response payload."""
    candidate_id: str = Field(description="Unique candidate identifier")
    total_results: int = Field(ge=0, description="Total matching jobs available after filtering")
    page: int = Field(default=1, ge=1, description="Current page number")
    limit: int = Field(default=20, ge=1, description="Maximum items requested per page")
    has_more: bool = Field(default=False, description="Whether more pages are available")
    generated_at: datetime = Field(default_factory=datetime.utcnow, description="UTC timestamp of feed generation")
    recommendations: List[RecommendedJobItem] = Field(
        default_factory=list,
        description="Ordered list of recommended job items (DAY 1 root field name)"
    )


class CandidateBehaviorHistory(BaseModel):
    """User interaction history for personalization."""
    saved_job_ids: List[str] = Field(default_factory=list, description="List of job IDs saved/bookmarked by candidate")
    applied_job_ids: List[str] = Field(default_factory=list, description="List of job IDs applied to by candidate")
    dismissed_job_ids: List[str] = Field(default_factory=list, description="List of job IDs explicitly dismissed/hidden by candidate")
    viewed_job_ids: List[str] = Field(default_factory=list, description="List of job IDs viewed by candidate")
