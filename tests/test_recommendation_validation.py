"""Focused acceptance checks for the Personalized Job Recommendations feature.

These tests deliberately exercise the public recommendation contracts with
controlled data in addition to the feature's existing unit and integration
coverage.  The two strict xfails document verified defects that require a
product decision or production fix; they must not be silently ignored.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.models.candidate import (
    Candidate,
    CandidatePreferences,
    CandidateProfileDetails,
    CandidateSkill,
    SkillLevel,
)
from src.repositories.behavior_repository import MockBehaviorRepository
from src.repositories.candidate_repository import candidate_repository
from src.repositories.mock_job_repository import MockJobRepository
from src.schemas.job import JobPosting, SkillRequirement
from src.schemas.recommendation import CandidateBehaviorHistory
from src.services.matching_service import MatchingService
from src.services.recommendation_scoring import (
    calculate_behavior_score,
    calculate_freshness_score,
    calculate_preference_fit,
    calculate_recommendation_score,
    calculate_role_fit,
)
from src.services.recommendation_service import RecommendationService


class StaticJobRepository:
    """Catalog test double; it deliberately has no candidate knowledge."""

    def __init__(self, jobs):
        self.jobs = jobs

    def get_active_jobs(self, work_mode=None, location=None, limit=None, offset=0):
        jobs = list(self.jobs)
        if work_mode:
            jobs = [job for job in jobs if job.work_mode == work_mode]
        if location:
            jobs = [job for job in jobs if job.location and location.lower() in job.location.lower()]
        return jobs[offset : offset + limit] if limit else jobs[offset:]


class TrackingMatchingService(MatchingService):
    """Proves recommendation scoring takes the deterministic matching route."""

    def __init__(self):
        super().__init__()
        self.evaluate_calls = 0
        self.normalize_calls = 0
        self.rule_calls = 0

    def normalize_job_requirements(self, raw_reqs):
        self.normalize_calls += 1
        return super().normalize_job_requirements(raw_reqs)

    def apply_evaluation_rules(self, response, required_skills):
        self.rule_calls += 1
        return super().apply_evaluation_rules(response, required_skills)

    def evaluate_match(self, *args, **kwargs):
        self.evaluate_calls += 1
        return super().evaluate_match(*args, **kwargs)


def _candidate(candidate_id="acceptance_candidate"):
    return Candidate(
        candidate_id=candidate_id,
        profile=CandidateProfileDetails(
            name="Acceptance Candidate",
            target_roles=["Backend Engineer"],
            preferences=CandidatePreferences(
                work_mode=["remote"], locations=["Cairo"], employment_type=["full_time"]
            ),
        ),
        skills=[
            CandidateSkill(skill_id="skill_python", name="Python", level=SkillLevel.ADVANCED),
            CandidateSkill(skill_id="skill_fastapi", name="FastAPI", level=SkillLevel.ADVANCED),
        ],
    )


def _job(job_id, title="Backend Developer", **overrides):
    values = {
        "job_id": job_id,
        "title": title,
        "company": "Acceptance Co",
        "canonical_role": title,
        "location": "Cairo",
        "work_mode": "remote",
        "employment_type": "full_time",
        "posted_at": datetime.now(timezone.utc),
        "required_skills": [
            SkillRequirement(skill_name="Python", proficiency="Advanced", is_critical=True),
            SkillRequirement(skill_name="FastAPI", proficiency="Advanced", is_critical=True),
        ],
    }
    values.update(overrides)
    return JobPosting(**values)


def test_formula_is_exact_and_components_are_bounded():
    score, breakdown = calculate_recommendation_score(90, 100, 100, 80, 50)

    # The values in the approval brief sum to 89.5 (not 88.5):
    # 54 + 15 + 10 + 8 + 2.5.
    assert score == 89.5
    assert breakdown.model_dump() == {
        "match_score": 90.0,
        "role_relevance_score": 100.0,
        "preference_fit_score": 100.0,
        "freshness_score": 80.0,
        "behavior_boost": 50.0,
    }

    bounded_score, bounded = calculate_recommendation_score(200, -1, 150, -5, 300)
    assert bounded_score == 75.0
    assert all(0.0 <= value <= 100.0 for value in bounded.model_dump().values())


@pytest.mark.parametrize(
    ("targets", "title", "expected"),
    [
        (["backend engineer"], "BACKEND-DEVELOPER!", 100.0),
        (["Machine Learning Engineer"], "Data Scientist", 75.0),
        (["Frontend Engineer"], "Backend Engineer", 45.0),
        (["Backend Engineer"], "HR Specialist", 10.0),
    ],
)
def test_role_fit_acceptance_cases(targets, title, expected):
    assert calculate_role_fit(targets, title) == expected


def test_role_fit_multiple_targets_and_experience_fallback():
    assert calculate_role_fit(["HR Specialist", "Backend Engineer"], "Backend Developer") == 100.0
    assert calculate_role_fit([], "Backend Developer", candidate_experience=[{"role": "Backend Engineer"}]) == 100.0
    assert calculate_role_fit([], "Backend Developer", candidate_experience=[]) == 50.0


def test_preference_and_freshness_acceptance_cases():
    prefs = {"work_mode": ["remote"], "locations": ["Cairo"], "employment_type": ["full_time"]}
    assert calculate_preference_fit(prefs, "remote", "Cairo", "full_time") == 100.0
    assert calculate_preference_fit(prefs, "onsite", "Riyadh", "contract") == 17.0
    assert calculate_preference_fit({}, "onsite", "Riyadh", "contract") == 50.0
    assert calculate_preference_fit(prefs, None, None, None) == 50.0
    assert calculate_preference_fit(prefs, None, "Cairo", "full_time") == 80.0
    assert calculate_preference_fit(prefs, "remote", "Cairo", None) == 87.5

    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    assert calculate_freshness_score(now, now) == 100.0
    assert calculate_freshness_score(now - timedelta(days=1), now) == 95.1
    assert calculate_freshness_score(now - timedelta(days=7), now) == 70.5
    assert calculate_freshness_score(now - timedelta(days=30), now) == 22.3
    assert calculate_freshness_score(None, now) == 50.0
    assert calculate_freshness_score(now - timedelta(days=10_000), now) == 0.0


def test_behavior_is_limited_to_the_weighted_component():
    job = _job("saved")
    assert calculate_behavior_score(CandidateBehaviorHistory(), job) == 50.0
    assert calculate_behavior_score(CandidateBehaviorHistory(saved_job_ids=["saved"]), job) == 100.0
    assert calculate_behavior_score(CandidateBehaviorHistory(applied_job_ids=["another"]), job) == 50.0

    high_behavior, _ = calculate_recommendation_score(90, 100, 100, 100, 100)
    low_behavior, _ = calculate_recommendation_score(90, 100, 100, 100, 0)
    assert high_behavior - low_behavior == 5.0


@pytest.mark.asyncio
async def test_complete_pipeline_reuses_matching_and_ranks_scores():
    strong = _job("strong")
    weak = _job("weak", title="Frontend Engineer", canonical_role="Frontend Engineer", required_skills=[])
    matching = TrackingMatchingService()
    service = RecommendationService(
        job_repository=StaticJobRepository([strong, weak]),
        behavior_repository=MockBehaviorRepository({}),
        matching_svc=matching,
    )

    feed = await service.get_recommendation_feed(_candidate(), limit=10)

    assert [item.job_id for item in feed.recommendations] == ["strong"]
    assert [item.rank for item in feed.recommendations] == [1]
    assert feed.recommendations[0].score == 97.5
    assert feed.recommendations[0].score_breakdown.match_score == 100.0
    assert matching.evaluate_calls == matching.normalize_calls == matching.rule_calls == 2


@pytest.mark.asyncio
async def test_min_score_zero_cannot_bypass_eligibility_and_order_is_deterministic():
    strong = _job("strong")
    stretch = _job(
        "stretch",
        title="AI Team Lead",
        required_skills=[
            SkillRequirement(skill_name="Python", proficiency="Advanced", is_critical=True),
            SkillRequirement(skill_name="C++", proficiency="Advanced", is_critical=True),
        ],
    )
    service = RecommendationService(
        job_repository=StaticJobRepository([stretch, strong]),
        behavior_repository=MockBehaviorRepository({}),
    )

    first = await service.get_recommendation_feed(_candidate(), limit=10, min_score=0)
    second = await service.get_recommendation_feed(_candidate(), limit=10, min_score=0)

    assert [item.job_id for item in first.recommendations] == ["strong", "stretch"]
    assert [item.job_id for item in first.recommendations] == [item.job_id for item in second.recommendations]
    assert first.recommendations[0].score_breakdown.match_score > first.recommendations[1].score_breakdown.match_score
    assert first.recommendations[1].explanation.headline.startswith("Partial match")


@pytest.mark.asyncio
async def test_candidate_filters_are_applied_after_catalog_retrieval():
    jobs = [_job("active"), _job("applied"), _job("dismissed")]
    behavior = CandidateBehaviorHistory(applied_job_ids=["applied"], dismissed_job_ids=["dismissed"])
    service = RecommendationService(
        job_repository=StaticJobRepository(jobs),
        behavior_repository=MockBehaviorRepository({"filter_candidate": behavior}),
    )

    feed = await service.get_recommendation_feed(_candidate("filter_candidate"))

    assert [item.job_id for item in feed.recommendations] == ["active"]


def test_mock_catalog_filters_inactive_and_expired_records():
    catalog_ids = {job.job_id for job in MockJobRepository().get_active_jobs()}

    assert "job_022" not in catalog_ids
    assert "job_024" not in catalog_ids
    assert "job_001" in catalog_ids


@pytest.mark.asyncio
async def test_explanation_reason_data_are_truthful():
    job = _job("explained")
    service = RecommendationService(job_repository=StaticJobRepository([job]))
    item = (await service.get_recommendation_feed(_candidate())).recommendations[0]

    assert "Python" in item.explanation.matched_skills
    assert "FastAPI" in item.explanation.matched_skills
    assert "High skill match" in item.reasons
    assert "Matches preferred work mode" in item.reasons
    assert "Matches preferred location" in item.reasons
    assert all(reason.text for reason in item.explanation.reasons)


def test_deduplication_keeps_the_newest_same_source_posting():
    now = datetime.now(timezone.utc)
    older = _job("old", source_url="https://example.test/jobs/1", posted_at=now - timedelta(days=7))
    newer = _job("new", source_url="https://example.test/jobs/1", posted_at=now - timedelta(days=1))

    deduped = RecommendationService().deduplicate_jobs([older, newer])

    assert [job.job_id for job in deduped] == ["new"]


def test_api_feed_is_personalized_and_rejects_unknown_candidates():
    client = TestClient(app)
    headers = {"X-API-Key": "test_api_key"}
    custom_candidate = Candidate(
        candidate_id="candidate_api_custom",
        profile=CandidateProfileDetails(
            name="Custom API Candidate",
            target_roles=["HR Specialist"],
            preferences=CandidatePreferences(work_mode=["onsite"]),
        ),
        skills=[],
    )
    candidate_repository.save_candidate(custom_candidate)

    from src.repositories.mock_job_repository import MockJobRepository
    from src.services.recommendation_service import recommendation_service

    original_repository = recommendation_service.job_repo
    recommendation_service.job_repo = MockJobRepository()
    try:
        known = client.get("/api/v1/recommendations/feed?candidate_id=candidate_api_custom", headers=headers)
        unknown = client.get("/api/v1/recommendations/feed?candidate_id=does_not_exist", headers=headers)
    finally:
        recommendation_service.job_repo = original_repository

    assert known.status_code == 200
    assert known.json()["candidate_id"] == "candidate_api_custom"
    assert known.json()["recommendations"] == []
    assert unknown.status_code == 404
