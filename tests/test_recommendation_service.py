"""End-to-end integration tests for Personalized Job Recommendations."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.models.candidate import (
    Candidate,
    CandidatePreferences,
    CandidateProfileDetails,
    CandidateSkill,
    EvidenceItem,
)
from src.repositories.behavior_repository import MockBehaviorRepository
from src.repositories.mock_job_repository import MockJobRepository
from src.services.recommendation_service import RecommendationService


@pytest.fixture
def python_senior_candidate():
    return Candidate(
        candidate_id="cand_python_senior",
        profile=CandidateProfileDetails(
            name="Ahmed Python",
            target_roles=["Backend Engineer"],
            preferences=CandidatePreferences(
                work_mode=["remote"],
                locations=["Riyadh", "Cairo"],
                employment_type=["full_time"],
            ),
        ),
        skills=[
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
                evidence=[EvidenceItem(text="Designed FastAPI REST APIs.")],
            ),
            CandidateSkill(
                skill_id="skill_sql",
                name="PostgreSQL",
                proficiency="advanced",
                confidence=0.90,
                evidence=[EvidenceItem(text="Postgres DB performance optimization.")],
            ),
            CandidateSkill(
                skill_id="skill_docker",
                name="Docker",
                proficiency="intermediate",
                confidence=0.85,
                evidence=[EvidenceItem(text="Containerized services.")],
            ),
            CandidateSkill(
                skill_id="skill_redis",
                name="Redis",
                proficiency="intermediate",
                confidence=0.85,
                evidence=[EvidenceItem(text="Caching layer with Redis.")],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_end_to_end_ranking_python_senior(python_senior_candidate):
    """
    Verify top recommendations for a Senior Python developer:
      - job_001 (Senior Python Backend Engineer, Remote) ranks #1.
      - Rank 1 score > Rank 2 score.
      - Match score >= 90.0.
      - Applied (job_028), dismissed (job_029), expired (job_022), inactive (job_024) are absent.
    """
    service = RecommendationService(
        job_repository=MockJobRepository(),
        behavior_repository=MockBehaviorRepository(),
    )
    feed = await service.get_recommendation_feed(python_senior_candidate, page=1, limit=20)

    assert len(feed.recommendations) > 0
    top_rec = feed.recommendations[0]

    # #1 Ranked job should be Senior Python Backend Engineer (job_001)
    assert top_rec.job_id == "job_001"
    assert top_rec.rank == 1
    assert top_rec.score_breakdown.match_score >= 90.0
    assert top_rec.score > feed.recommendations[1].score
    assert len(top_rec.reasons) > 0
    assert "Python" in top_rec.explanation.matched_skills

    # Assert excluded jobs are definitely not in recommendations
    recommended_ids = {r.job_id for r in feed.recommendations}
    assert "job_028" not in recommended_ids, "Applied job_028 was not filtered"
    assert "job_029" not in recommended_ids, "Dismissed job_029 was not filtered"
    assert "job_022" not in recommended_ids, "Expired job_022 was not filtered"
    assert "job_024" not in recommended_ids, "Inactive job_024 was not filtered"


@pytest.mark.asyncio
async def test_recommendation_pagination(python_senior_candidate):
    """Verify limit and page offsets deliver deterministic, non-overlapping subsets."""
    service = RecommendationService(
        job_repository=MockJobRepository(),
        behavior_repository=MockBehaviorRepository(),
    )

    page1 = await service.get_recommendation_feed(python_senior_candidate, page=1, limit=3)
    assert len(page1.recommendations) == 3
    assert page1.page == 1
    assert page1.limit == 3
    assert page1.total_results >= 3

    page1_ids = [r.job_id for r in page1.recommendations]

    page2 = await service.get_recommendation_feed(python_senior_candidate, page=2, limit=3)
    assert len(page2.recommendations) == 3
    assert page2.page == 2

    page2_ids = [r.job_id for r in page2.recommendations]

    # Pages must be completely disjoint
    assert set(page1_ids).isdisjoint(set(page2_ids))


def test_recommendation_api_endpoint(python_senior_candidate):
    """Verify GET /api/v1/recommendations/feed works via FastAPI TestClient."""
    from src.repositories.candidate_repository import candidate_repository
    candidate_repository.save_candidate(python_senior_candidate)

    client = TestClient(app)
    response = client.get(f"/api/v1/recommendations/feed?candidate_id={python_senior_candidate.candidate_id}&limit=5")
    assert response.status_code == 200

    data = response.json()
    assert "recommendations" in data
    assert "total_results" in data
    assert len(data["recommendations"]) <= 5
    if len(data["recommendations"]) > 0:
        first = data["recommendations"][0]
        assert "job_id" in first
        assert "score" in first
        assert "score_breakdown" in first
        assert "explanation" in first
        assert "reasons" in first
        assert first["rank"] == 1
