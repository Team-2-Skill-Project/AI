"""Unit tests for deterministic recommendation scoring algorithms."""

import pytest
from datetime import datetime, timezone, timedelta
from src.services.recommendation_scoring import (
    calculate_role_fit,
    calculate_preference_fit,
    calculate_freshness_score,
    calculate_behavior_score,
    calculate_recommendation_score,
)
from src.models.candidate import CandidatePreferences, ExperienceItem
from src.schemas.recommendation import CandidateBehaviorHistory


def test_role_fit_direct_match():
    """Verify exact and normalized synonym matches yield 100.0."""
    score = calculate_role_fit(["Backend Engineer"], "Backend Developer")
    assert score == 100.0

    score2 = calculate_role_fit(["Senior Python Developer"], "Python Developer")
    assert score2 == 100.0

    score3 = calculate_role_fit(["Software Engineer"], "Software Developer")
    assert score3 == 100.0


def test_role_fit_adjacent_role_family():
    """Verify adjacent roles in the same family (e.g. Data/AI) yield 75.0."""
    score = calculate_role_fit(["Machine Learning Engineer"], "Data Scientist")
    assert score == 75.0

    score2 = calculate_role_fit(
        ["AI Engineer"],
        "Data Scientist",
        job_role_family="Data & AI"
    )
    assert score2 == 75.0


def test_role_fit_transferable_technical():
    """Verify transferable engineering roles yield 45.0."""
    score = calculate_role_fit(["Frontend Engineer"], "Backend Engineer")
    assert score == 45.0

    score2 = calculate_role_fit(["DevOps Engineer"], "Software Engineer")
    assert score2 == 45.0


def test_role_fit_unrelated_role():
    """Verify completely unrelated roles yield 10.0."""
    score = calculate_role_fit(["Backend Engineer"], "HR Specialist")
    assert score == 10.0

    score2 = calculate_role_fit(["Python Developer"], "UI/UX Designer")
    assert score2 == 10.0


def test_role_fit_fallbacks():
    """Verify fallback to candidate work history or neutral 50.0."""
    # Fallback to experience
    exp = [ExperienceItem(role="Backend Engineer", company="Tech Co")]
    score = calculate_role_fit(candidate_target_roles=[], job_title="Backend Developer", candidate_experience=exp)
    assert score == 100.0

    # No roles and no experience -> 50.0
    score_neutral = calculate_role_fit(candidate_target_roles=[], job_title="Backend Developer", candidate_experience=[])
    assert score_neutral == 50.0


def test_preference_fit_scoring():
    """Verify preference matching across work mode, location, and employment type."""
    prefs = CandidatePreferences(
        work_mode=["remote"],
        locations=["Riyadh", "Cairo"],
        employment_type=["full_time"]
    )

    # Full match
    score_full = calculate_preference_fit(prefs, job_work_mode="remote", job_location="Riyadh", job_employment_type="full_time")
    assert score_full == 100.0

    # Work mode mismatch (Onsite when preferred Remote)
    score_wm_mismatch = calculate_preference_fit(prefs, job_work_mode="onsite", job_location="Riyadh", job_employment_type="full_time")
    # 0.40 * 0 + 0.35 * 100 + 0.25 * 100 = 60.0
    assert score_wm_mismatch == 60.0

    # Empty candidate preferences -> neutral 50.0
    empty_prefs = CandidatePreferences()
    assert calculate_preference_fit(empty_prefs, job_work_mode="onsite", job_location="Tokyo") == 50.0
    assert calculate_preference_fit(None, job_work_mode="onsite") == 50.0


def test_freshness_decay_scoring():
    """Verify mathematical output of exponential freshness decay."""
    now = datetime.now(timezone.utc)

    # 0 days (Today) -> 100.0
    assert calculate_freshness_score(now, now_dt=now) == 100.0

    # 7 days ago -> ~70.5
    seven_days_ago = now - timedelta(days=7)
    score_7 = calculate_freshness_score(seven_days_ago, now_dt=now)
    assert 70.0 <= score_7 <= 71.0

    # 14 days ago -> ~49.6
    fourteen_days_ago = now - timedelta(days=14)
    score_14 = calculate_freshness_score(fourteen_days_ago, now_dt=now)
    assert 49.0 <= score_14 <= 50.0

    # 30 days ago -> ~22.3
    thirty_days_ago = now - timedelta(days=30)
    score_30 = calculate_freshness_score(thirty_days_ago, now_dt=now)
    assert 22.0 <= score_30 <= 23.0

    # Missing posted_at is neutral
    assert calculate_freshness_score(None) == 50.0


def test_behavior_scoring():
    """Verify behavior score ranges and cold-start baseline."""
    # Cold start / no behavior -> 50.0
    behavior_empty = CandidateBehaviorHistory()
    job_mock = {"job_id": "job_100"}
    assert calculate_behavior_score(behavior_empty, job_mock) == 50.0
    assert calculate_behavior_score(None, job_mock) == 50.0

    # Saved this exact job -> 100.0
    behavior_saved = CandidateBehaviorHistory(saved_job_ids=["job_100"])
    assert calculate_behavior_score(behavior_saved, job_mock) == 100.0

    # Unrelated activity does not imply affinity for this job
    behavior_active = CandidateBehaviorHistory(saved_job_ids=["job_999"])
    assert calculate_behavior_score(behavior_active, job_mock) == 50.0


def test_composite_recommendation_score():
    """Verify composite weighting formula 0.60/0.15/0.10/0.10/0.05."""
    # Perfect scores across all dimensions
    score_perfect, breakdown = calculate_recommendation_score(
        match_score=100.0,
        role_fit=100.0,
        preference_fit=100.0,
        freshness_score=100.0,
        behavior_score=100.0,
    )
    assert score_perfect == 100.0
    assert breakdown.match_score == 100.0

    # Cold start baseline behavior (50.0) contributes exactly 2.5 points
    score_cold, breakdown_cold = calculate_recommendation_score(
        match_score=80.0,    # 0.60 * 80 = 48.0
        role_fit=100.0,      # 0.15 * 100 = 15.0
        preference_fit=100.0,# 0.10 * 100 = 10.0
        freshness_score=100.0,# 0.10 * 100 = 10.0
        behavior_score=50.0, # 0.05 * 50 = 2.5
    )
    # 48 + 15 + 10 + 10 + 2.5 = 85.5
    assert score_cold == 85.5
    assert breakdown_cold.behavior_boost == 50.0

    # Match score dominance: high match + old job vs low match + fresh job
    score_high_match_old, _ = calculate_recommendation_score(
        match_score=95.0, role_fit=100.0, preference_fit=100.0, freshness_score=20.0, behavior_score=50.0
    )
    score_low_match_fresh, _ = calculate_recommendation_score(
        match_score=30.0, role_fit=50.0, preference_fit=100.0, freshness_score=100.0, behavior_score=50.0
    )
    assert score_high_match_old > score_low_match_fresh
    assert score_high_match_old == 86.5
    assert score_low_match_fresh == 48.0
