"""API-level automation coverage for Personalized Job Recommendations."""

from fastapi.testclient import TestClient

from src.api.main import app
from src.models.candidate import (
    Candidate,
    CandidateProfileDetails,
    CandidatePreferences,
    CandidateSkill,
    SkillLevel,
)
from src.repositories.behavior_repository import MockBehaviorRepository
from src.repositories.candidate_repository import candidate_repository
from src.repositories.mock_job_repository import MockJobRepository
from src.schemas.recommendation import CandidateBehaviorHistory
from src.services.recommendation_service import recommendation_service


def _automation_candidate() -> Candidate:
    return Candidate(
        candidate_id="automation_recommendation_candidate",
        profile=CandidateProfileDetails(
            name="Automation Candidate",
            target_roles=["Backend Engineer"],
            preferences=CandidatePreferences(
                work_mode=["remote"],
                locations=["Riyadh", "Cairo"],
                employment_type=["full_time"],
            ),
        ),
        skills=[
            CandidateSkill(skill_id="python", name="Python", level=SkillLevel.EXPERT),
            CandidateSkill(skill_id="fastapi", name="FastAPI", level=SkillLevel.ADVANCED),
            CandidateSkill(skill_id="postgresql", name="PostgreSQL", level=SkillLevel.ADVANCED),
            CandidateSkill(skill_id="docker", name="Docker", level=SkillLevel.INTERMEDIATE),
        ],
    )


def test_personalized_recommendations_api_automation(monkeypatch):
    """Exercise the public feed contract with deterministic local job data."""
    candidate = _automation_candidate()
    original_get_candidate = candidate_repository.get_candidate

    monkeypatch.setattr(
        candidate_repository,
        "get_candidate",
        lambda candidate_id: candidate if candidate_id == candidate.candidate_id else original_get_candidate(candidate_id),
    )
    monkeypatch.setattr(recommendation_service, "job_repo", MockJobRepository())
    monkeypatch.setattr(
        recommendation_service,
        "behavior_repo",
        MockBehaviorRepository({candidate.candidate_id: CandidateBehaviorHistory(saved_job_ids=["job_001"])}),
    )

    client = TestClient(app)
    headers = {"X-API-Key": "test_api_key"}
    response = client.get(
        f"/api/v1/recommendations/feed?candidate_id={candidate.candidate_id}&limit=50&min_score=0",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    recommendations = payload["recommendations"]
    assert payload["candidate_id"] == candidate.candidate_id
    assert payload["total_results"] == len(recommendations)
    assert 0 < len(recommendations) <= 50

    scores = [item["score"] for item in recommendations]
    assert scores == sorted(scores, reverse=True)
    assert [item["rank"] for item in recommendations] == list(range(1, len(recommendations) + 1))
    assert recommendations[0]["score_breakdown"]["match_score"] >= 90.0
    assert "job_001" in {item["job_id"] for item in recommendations}

    for item in recommendations:
        assert item["qualification_status"] in {"Qualified", "Partially Qualified"}
        assert item["score_breakdown"]["match_score"] > 0.0
        assert "Strong match" not in item["explanation"]["headline"] or item["score_breakdown"]["match_score"] >= 80.0
        assert item["explanation"]["matched_skills"]

    page_one = client.get(
        f"/api/v1/recommendations/feed?candidate_id={candidate.candidate_id}&page=1&limit=1",
        headers=headers,
    ).json()
    page_two = client.get(
        f"/api/v1/recommendations/feed?candidate_id={candidate.candidate_id}&page=2&limit=1",
        headers=headers,
    ).json()
    assert page_one["recommendations"]
    assert page_two["recommendations"]
    assert page_one["recommendations"][0]["job_id"] != page_two["recommendations"][0]["job_id"]

    high_cutoff = client.get(
        f"/api/v1/recommendations/feed?candidate_id={candidate.candidate_id}&min_score=100",
        headers=headers,
    )
    assert high_cutoff.status_code == 200
    assert high_cutoff.json()["recommendations"] == []
