"""Integration tests for real candidate integration with personalized job recommendations."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.models.candidate import (
    Candidate,
    CandidatePreferences,
    CandidateProfile,
    CandidateSkill,
    EvidenceItem,
    ExperienceItem,
    UserProfile,
)
from src.repositories.candidate_repository import candidate_repository
from src.repositories.mock_job_repository import MockJobRepository
from src.schemas.job import JobPosting, SkillRequirement
from src.services.recommendation_service import RecommendationService, recommendation_service


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "test_api_key"}


@pytest.fixture
def real_backend_candidate():
    """Candidate with Python / FastAPI backend skills."""
    return Candidate(
        candidate_id="cand_real_backend_001",
        user=UserProfile(name="Tariq Backend", email="tariq@backend.test"),
        candidate_profile=CandidateProfile(
            headline="Senior Python Backend Engineer",
            location="Riyadh, Saudi Arabia",
        ),
        target_roles=["Backend Engineer"],
        preferences=CandidatePreferences(
            work_mode=["remote"],
            locations=["Riyadh"],
            employment_type=["full_time"],
        ),
        candidate_skills=[
            CandidateSkill(
                skill_id="skill_python",
                name="Python",
                proficiency="expert",
                confidence=0.95,
                evidence=[EvidenceItem(text="7 years Python microservices experience.")],
            ),
            CandidateSkill(
                skill_id="skill_fastapi",
                name="FastAPI",
                proficiency="advanced",
                confidence=0.90,
                evidence=[EvidenceItem(text="Engineered FastAPI microservices.")],
            ),
            CandidateSkill(
                skill_id="skill_postgresql",
                name="PostgreSQL",
                proficiency="advanced",
                confidence=0.90,
                evidence=[EvidenceItem(text="PostgreSQL database architecture.")],
            ),
        ],
        experiences=[
            ExperienceItem(
                company_name="Cloud Arabia",
                job_title="Backend Engineer",
                employment_type="full-time",
                start_date="2020-01",
                end_date="2024-01",
                is_current=False,
                technologies=["Python", "FastAPI", "PostgreSQL"],
            ),
        ],
    )


@pytest.fixture
def real_frontend_candidate():
    """Candidate with React / TypeScript frontend skills."""
    return Candidate(
        candidate_id="cand_real_frontend_002",
        user=UserProfile(name="Sara Frontend", email="sara@frontend.test"),
        candidate_profile=CandidateProfile(
            headline="Frontend Engineer",
            location="Cairo, Egypt",
        ),
        target_roles=["Frontend Engineer"],
        preferences=CandidatePreferences(
            work_mode=["hybrid"],
            locations=["Cairo"],
            employment_type=["full_time"],
        ),
        candidate_skills=[
            CandidateSkill(
                skill_id="skill_react",
                name="React",
                proficiency="expert",
                confidence=0.95,
                evidence=[EvidenceItem(text="5 years React Single Page App development.")],
            ),
            CandidateSkill(
                skill_id="skill_typescript",
                name="TypeScript",
                proficiency="advanced",
                confidence=0.90,
                evidence=[EvidenceItem(text="TypeScript web UI components.")],
            ),
        ],
        experiences=[
            ExperienceItem(
                company_name="Web Works",
                job_title="Frontend Developer",
                employment_type="full-time",
                start_date="2021-06",
                end_date="2024-06",
                is_current=False,
                technologies=["React", "TypeScript"],
            ),
        ],
    )


def test_recommendation_feed_requires_candidate_id(test_client, auth_headers):
    """The endpoint must require candidate_id and return 422 if omitted."""
    # Query without candidate_id
    response = test_client.get("/api/v1/recommendations/feed", headers=auth_headers)
    assert response.status_code == 422
    assert "candidate_id" in response.text


def test_missing_candidate_returns_404_and_never_falls_back(test_client, auth_headers):
    """A non-existent candidate must return 404 and must never silently fall back to cand_001."""
    non_existent_id = "non_existent_cand_99999"
    response = test_client.get(
        f"/api/v1/recommendations/feed?candidate_id={non_existent_id}",
        headers=auth_headers,
    )
    assert response.status_code == 404
    detail = response.json().get("detail", "")
    assert non_existent_id in detail
    assert "not found" in detail.lower()


def test_persisted_candidate_receives_personalized_recommendations(
    test_client, auth_headers, real_backend_candidate, monkeypatch
):
    """Test that a persisted candidate receives personalized recommendations from their real data."""
    # Persist the real candidate
    candidate_repository.save_candidate(real_backend_candidate)

    # Use deterministic mock job catalog to verify ranking logic
    monkeypatch.setattr(recommendation_service, "job_repo", MockJobRepository())

    response = test_client.get(
        f"/api/v1/recommendations/feed?candidate_id={real_backend_candidate.candidate_id}&limit=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["candidate_id"] == real_backend_candidate.candidate_id
    recommendations = data["recommendations"]
    assert len(recommendations) > 0

    # Top recommendation for backend engineer should match Python / Backend
    top_job = recommendations[0]
    assert top_job["rank"] == 1
    assert "Python" in top_job["explanation"]["matched_skills"]
    assert top_job["score_breakdown"]["match_score"] >= 80.0


def test_two_candidates_remain_isolated_in_recommendations(
    test_client, auth_headers, real_backend_candidate, real_frontend_candidate, monkeypatch
):
    """Recommendations for two distinct candidates must remain strictly isolated."""
    # Persist both candidates
    candidate_repository.save_candidate(real_backend_candidate)
    candidate_repository.save_candidate(real_frontend_candidate)

    # Setup job catalog with one backend job and one frontend job
    backend_job = JobPosting(
        job_id="job_py_backend",
        title="Senior Python Backend Developer",
        company="PyCorp",
        location="Riyadh",
        work_mode="remote",
        employment_type="full_time",
        posted_at=datetime.now(timezone.utc),
        required_skills=[
            SkillRequirement(skill_name="Python", proficiency="Expert", is_critical=True),
            SkillRequirement(skill_name="FastAPI", proficiency="Advanced", is_critical=True),
        ],
    )
    frontend_job = JobPosting(
        job_id="job_fe_react",
        title="Senior React Frontend Developer",
        company="ReactCorp",
        location="Cairo",
        work_mode="hybrid",
        employment_type="full_time",
        posted_at=datetime.now(timezone.utc),
        required_skills=[
            SkillRequirement(skill_name="React", proficiency="Expert", is_critical=True),
            SkillRequirement(skill_name="TypeScript", proficiency="Advanced", is_critical=True),
        ],
    )

    class TwoJobRepo:
        def get_active_jobs(self, work_mode=None, location=None, limit=None, offset=0):
            jobs = [backend_job, frontend_job]
            if work_mode:
                jobs = [j for j in jobs if j.work_mode == work_mode]
            if location:
                jobs = [j for j in jobs if j.location and location.lower() in j.location.lower()]
            return jobs

    monkeypatch.setattr(recommendation_service, "job_repo", TwoJobRepo())

    # Feed for Backend candidate
    res_backend = test_client.get(
        f"/api/v1/recommendations/feed?candidate_id={real_backend_candidate.candidate_id}",
        headers=auth_headers,
    )
    assert res_backend.status_code == 200
    feed_backend = res_backend.json()
    assert feed_backend["candidate_id"] == real_backend_candidate.candidate_id
    backend_recs = feed_backend["recommendations"]
    assert len(backend_recs) == 1
    assert backend_recs[0]["job_id"] == "job_py_backend"
    assert "Python" in backend_recs[0]["explanation"]["matched_skills"]

    # Feed for Frontend candidate
    res_frontend = test_client.get(
        f"/api/v1/recommendations/feed?candidate_id={real_frontend_candidate.candidate_id}",
        headers=auth_headers,
    )
    assert res_frontend.status_code == 200
    feed_frontend = res_frontend.json()
    assert feed_frontend["candidate_id"] == real_frontend_candidate.candidate_id
    frontend_recs = feed_frontend["recommendations"]
    assert len(frontend_recs) == 1
    assert frontend_recs[0]["job_id"] == "job_fe_react"
    assert "React" in frontend_recs[0]["explanation"]["matched_skills"]


@pytest.mark.asyncio
async def test_recommendation_service_rejects_missing_or_blank_candidate_id():
    """RecommendationService.get_recommendation_feed raises ValueError when candidate_id is missing."""
    service = RecommendationService()

    # Candidate with empty candidate_id
    invalid_candidate = Candidate(
        candidate_id="",
        user=UserProfile(name="No ID"),
    )

    with pytest.raises(ValueError, match="valid candidate_id"):
        await service.get_recommendation_feed(invalid_candidate)

    # Dict without candidate_id
    with pytest.raises(ValueError, match="valid candidate_id"):
        await service.get_recommendation_feed({"user": {"name": "No ID"}})
