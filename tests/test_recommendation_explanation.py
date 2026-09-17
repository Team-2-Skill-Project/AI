"""Unit tests for deterministic recommendation reason generation."""

import pytest
from src.schemas.job import JobPosting
from src.schemas.match import SkillGapAnalysisResponse, SkillMatchItem, QualificationStatus
from src.schemas.recommendation import ScoreBreakdown
from src.models.candidate import CandidatePreferences
from src.services.recommendation_explanation import build_recommendation_explanation


def test_build_explanation_high_skill_and_target_role():
    """Verify high skill match and target role produce factual, structured reasons."""
    job = JobPosting(
        job_id="job_001",
        title="Senior Python Backend Engineer",
        company="CloudScale",
        work_mode="remote",
        location="Riyadh",
    )

    match_result = SkillGapAnalysisResponse(
        job_id="job_001",
        candidate_id="cand_001",
        overall_match_score=90.0,
        qualification_status=QualificationStatus.QUALIFIED.value,
        full_candidate_summary="Summary",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Python",
                required_proficiency="Advanced",
                candidate_proficiency="Advanced",
                match_score=90.0,
                is_matched=True,
                skill_feedback="Matches",
                evidence_found="Years of Python",
            ),
            SkillMatchItem(
                skill_name="FastAPI",
                required_proficiency="Advanced",
                candidate_proficiency="Intermediate",
                match_score=75.0,
                is_matched=True,
                skill_feedback="Matches",
                evidence_found="Built APIs",
            ),
            SkillMatchItem(
                skill_name="Kubernetes",
                required_proficiency="Intermediate",
                candidate_proficiency="Missing",
                match_score=0.0,
                is_matched=False,
                skill_feedback="Missing",
                evidence_found="None",
            ),
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=[],
    )

    score_breakdown = ScoreBreakdown(
        match_score=90.0,
        role_relevance_score=100.0,
        preference_fit_score=100.0,
        freshness_score=95.0,
        behavior_boost=100.0,
    )

    prefs = CandidatePreferences(work_mode=["remote"], locations=["Riyadh"])

    day1_reasons, structured = build_recommendation_explanation(
        job=job,
        match_result=match_result,
        score_breakdown=score_breakdown,
        candidate_target_roles=["Backend Engineer"],
        candidate_preferences=prefs,
        is_saved=True,
    )

    # Verify Day 1 string reasons
    assert "High skill match" in day1_reasons
    assert "Matches target role" in day1_reasons
    assert "Matches preferred work mode" in day1_reasons
    assert "Matches preferred location" in day1_reasons
    assert "Recently posted" in day1_reasons
    assert "You saved a similar opportunity" in day1_reasons

    # Verify structured attributes
    assert "Python" in structured.matched_skills
    assert "FastAPI" in structured.matched_skills
    assert "Kubernetes" in structured.missing_skills
    assert len(structured.reasons) >= 5

    reason_codes = [r.code for r in structured.reasons]
    assert "SKILL_MATCH_HIGH" in reason_codes
    assert "TARGET_ROLE_MATCH" in reason_codes
    assert "WORK_MODE_MATCH" in reason_codes
    assert "SAVED_OPPORTUNITY" in reason_codes


def test_build_explanation_no_hallucinations_on_missing_skills():
    """Verify missing skills are correctly isolated and not falsely claimed as matched."""
    job = JobPosting(job_id="job_002", title="DevOps Engineer")

    match_result = SkillGapAnalysisResponse(
        job_id="job_002",
        candidate_id="cand_001",
        overall_match_score=0.0,
        qualification_status=QualificationStatus.NOT_QUALIFIED.value,
        full_candidate_summary="Summary",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Kubernetes",
                required_proficiency="Advanced",
                candidate_proficiency="Missing",
                match_score=0.0,
                is_matched=False,
                skill_feedback="Missing",
                evidence_found="None",
            )
        ],
        missing_critical_skills=["Kubernetes"],
        recommended_upskilling_path=[],
    )

    score_breakdown = ScoreBreakdown(
        match_score=0.0,
        role_relevance_score=10.0,
        preference_fit_score=100.0,
        freshness_score=50.0,
        behavior_boost=50.0,
    )

    day1_reasons, structured = build_recommendation_explanation(
        job=job,
        match_result=match_result,
        score_breakdown=score_breakdown,
        candidate_target_roles=["Backend Engineer"],
    )

    assert "Kubernetes" in structured.missing_skills
    assert len(structured.matched_skills) == 0
    assert "High skill match" not in day1_reasons


def test_weak_match_never_gets_strong_match_headline():
    job = JobPosting(job_id="job_003", title="AI Team Lead", company="Example")
    match_result = SkillGapAnalysisResponse(
        job_id="job_003",
        candidate_id="cand_001",
        overall_match_score=25.0,
        qualification_status=QualificationStatus.PARTIALLY_QUALIFIED.value,
        full_candidate_summary="Summary",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Python",
                required_proficiency="Advanced",
                candidate_proficiency="Advanced",
                match_score=100.0,
                is_matched=True,
                skill_feedback="Matches",
                evidence_found="Python experience",
            )
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=[],
    )
    _, structured = build_recommendation_explanation(
        job=job,
        match_result=match_result,
        score_breakdown=ScoreBreakdown(
            match_score=25.0,
            role_relevance_score=45.0,
            preference_fit_score=50.0,
            freshness_score=50.0,
        ),
    )

    assert "Strong match" not in structured.headline
    assert "Partial match" in structured.headline
