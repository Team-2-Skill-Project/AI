"""Deterministic reason generation for Personalized Job Recommendations.

Constructs factual, evidence-grounded 'Recommended because...' reasons
directly from match evaluations, candidate preferences, role alignments,
and behavior signals without any LLM hallucination.
"""

from typing import List, Optional, Any, Tuple
from src.schemas.recommendation import (
    RecommendationExplanation,
    RecommendationReason,
    ScoreBreakdown,
)
from src.schemas.match import SkillGapAnalysisResponse


def build_recommendation_explanation(
    job: Any,
    match_result: SkillGapAnalysisResponse,
    score_breakdown: ScoreBreakdown,
    candidate_target_roles: Optional[List[str]] = None,
    candidate_preferences: Optional[Any] = None,
    is_saved: bool = False,
) -> Tuple[List[str], RecommendationExplanation]:
    """
    Builds both concise Day 1 string reasons and rich structured explanation metadata.
    
    Returns:
        (day1_reasons_list, structured_explanation)
    """
    reasons_list: List[str] = []
    structured_reasons: List[RecommendationReason] = []

    matched_skills: List[str] = []
    missing_skills: List[str] = []

    # 1. Extract Matched & Missing Skills from MatchResult
    for item in match_result.skill_breakdown:
        if item.is_matched:
            matched_skills.append(item.skill_name)
        else:
            missing_skills.append(item.skill_name)

    # 2. Skill Match Reasons
    if match_result.overall_match_score >= 80.0:
        top_matched_str = ", ".join(matched_skills[:3]) if matched_skills else "core skills"
        reasons_list.append("High skill match")
        structured_reasons.append(
            RecommendationReason(
                code="SKILL_MATCH_HIGH",
                category="skills",
                text=f"Strong skill match ({round(match_result.overall_match_score)}% match on {top_matched_str})",
                weight="primary",
            )
        )
    elif match_result.overall_match_score >= 60.0:
        reasons_list.append("Good skill qualification")
        structured_reasons.append(
            RecommendationReason(
                code="SKILL_MATCH_MODERATE",
                category="skills",
                text=f"Good technical qualification matching {len(matched_skills)} required skills",
                weight="secondary",
            )
        )

    # 3. Role Fit Reasons
    job_title = getattr(job, "title", "") if hasattr(job, "title") else job.get("title", "")
    if score_breakdown.role_relevance_score >= 75.0:
        reasons_list.append("Matches target role")
        target_str = candidate_target_roles[0] if candidate_target_roles else job_title
        structured_reasons.append(
            RecommendationReason(
                code="TARGET_ROLE_MATCH",
                category="role",
                text=f"Directly matches target role trajectory '{target_str}'",
                weight="primary",
            )
        )
    elif score_breakdown.role_relevance_score >= 45.0:
        structured_reasons.append(
            RecommendationReason(
                code="ADJACENT_ROLE_FIT",
                category="role",
                text="Transferable engineering role with strong skill overlap",
                weight="supporting",
            )
        )

    # 4. Preference Fit Reasons
    job_work_mode = getattr(job, "work_mode", None) if hasattr(job, "work_mode") else job.get("work_mode")
    job_location = getattr(job, "location", None) if hasattr(job, "location") else job.get("location")

    if candidate_preferences:
        pref_work_modes = getattr(candidate_preferences, "work_mode", []) or []
        pref_locations = getattr(candidate_preferences, "locations", []) or []

        if isinstance(candidate_preferences, dict):
            pref_work_modes = candidate_preferences.get("work_mode", []) or []
            pref_locations = candidate_preferences.get("locations", []) or []

        if job_work_mode and pref_work_modes and job_work_mode.lower() in [m.lower() for m in pref_work_modes]:
            reasons_list.append("Matches preferred work mode")
            structured_reasons.append(
                RecommendationReason(
                    code="WORK_MODE_MATCH",
                    category="preference",
                    text=f"Matches preferred work mode ({job_work_mode.title()})",
                    weight="supporting",
                )
            )

        if job_location and pref_locations and any(pl.lower() in job_location.lower() for pl in pref_locations):
            reasons_list.append("Matches preferred location")
            structured_reasons.append(
                RecommendationReason(
                    code="LOCATION_MATCH",
                    category="preference",
                    text=f"Matches preferred location ({job_location})",
                    weight="supporting",
                )
            )

    # 5. Freshness Reasons
    if score_breakdown.freshness_score >= 90.0:
        reasons_list.append("Recently posted")
        structured_reasons.append(
            RecommendationReason(
                code="RECENTLY_POSTED",
                category="freshness",
                text="Recently posted opportunity",
                weight="supporting",
            )
        )

    # 6. Behavior Reasons
    if is_saved:
        reasons_list.append("You saved a similar opportunity")
        structured_reasons.append(
            RecommendationReason(
                code="SAVED_OPPORTUNITY",
                category="behavior",
                text="You saved this opportunity in your bookmarks",
                weight="supporting",
            )
        )

    # Ensure at least one fallback reason exists
    if not reasons_list:
        reasons_list.append("Recommended based on candidate profile")
        structured_reasons.append(
            RecommendationReason(
                code="PROFILE_FIT",
                category="skills",
                text="Recommended based on candidate profile match",
                weight="supporting",
            )
        )

    # Headline generation
    if matched_skills:
        headline = f"Strong match for your {', '.join(matched_skills[:2])} background"
    elif score_breakdown.role_relevance_score >= 75.0:
        headline = f"Aligned with your target role as {job_title}"
    else:
        headline = f"Recommended opportunity at {getattr(job, 'company', 'company') or 'company'}"

    explanation = RecommendationExplanation(
        headline=headline,
        reasons=structured_reasons,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
    )

    return reasons_list, explanation
