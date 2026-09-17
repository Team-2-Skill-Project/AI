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
    SkillLevel,
)
from src.services.recommendation_service import RecommendationService
from src.repositories.mock_job_repository import MockJobRepository


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
                level=SkillLevel.EXPERT,
                confidence=0.95,
                evidence=[EvidenceItem(text="7 years Python microservices experience.")],
            ),
            CandidateSkill(
                skill_id="skill_fastapi",
                name="FastAPI",
                level=SkillLevel.ADVANCED,
                confidence=0.90,
                evidence=[EvidenceItem(text="Designed FastAPI REST APIs.")],
            ),
            CandidateSkill(
                skill_id="skill_sql",
                name="PostgreSQL",
                level=SkillLevel.ADVANCED,
                confidence=0.90,
                evidence=[EvidenceItem(text="Postgres DB performance optimization.")],
            ),
            CandidateSkill(
                skill_id="skill_docker",
                name="Docker",
                level=SkillLevel.INTERMEDIATE,
                confidence=0.85,
                evidence=[EvidenceItem(text="Containerized services.")],
            ),
            CandidateSkill(
                skill_id="skill_redis",
                name="Redis",
                level=SkillLevel.INTERMEDIATE,
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
    service = RecommendationService(job_repository=MockJobRepository())
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

    rec_job_ids = [r.job_id for r in feed.recommendations]

    # Verify Hard Filters
    assert "job_028" not in rec_job_ids  # Applied job
    assert "job_029" not in rec_job_ids  # Dismissed job
    assert "job_022" not in rec_job_ids  # Expired job
    assert "job_024" not in rec_job_ids  # Inactive job

    # Verify Saved job indicator
    saved_items = [r for r in feed.recommendations if r.job_id == "job_030"]
    if saved_items:
        assert saved_items[0].is_saved is True


@pytest.mark.asyncio
async def test_recommendation_pagination(python_senior_candidate):
    """Verify pagination slices items cleanly without duplicate rank overlap."""
    service = RecommendationService(job_repository=MockJobRepository())

    # Page 1 (limit 3)
    page1 = await service.get_recommendation_feed(python_senior_candidate, page=1, limit=3)
    assert len(page1.recommendations) == 3
    assert page1.page == 1
    assert page1.has_more is True
    assert page1.recommendations[0].rank == 1
    assert page1.recommendations[2].rank == 3

    # Page 2 (limit 3)
    page2 = await service.get_recommendation_feed(python_senior_candidate, page=2, limit=3)
    assert len(page2.recommendations) == 3
    assert page2.page == 2
    assert page2.recommendations[0].rank == 4
    assert page2.recommendations[2].rank == 6

    # Verify no ID overlap between pages
    page1_ids = {r.job_id for r in page1.recommendations}
    page2_ids = {r.job_id for r in page2.recommendations}
    assert page1_ids.isdisjoint(page2_ids)


def test_recommendation_api_endpoint():
    """Verify GET /api/v1/recommendations/feed works via FastAPI TestClient."""
    client = TestClient(app)

    headers = {"X-API-Key": "test_api_key"}
    response = client.get("/api/v1/recommendations/feed?candidate_id=cand_001&limit=5", headers=headers)

    assert response.status_code == 200
    data = response.json()

    assert data["candidate_id"] == "cand_001"
    assert "recommendations" in data
    assert isinstance(data["recommendations"], list)
    assert len(data["recommendations"]) <= 5

    if data["recommendations"]:
        first_item = data["recommendations"][0]
        assert "job_id" in first_item
        assert "rank" in first_item
        assert "score" in first_item
        assert "reasons" in first_item
        assert "score_breakdown" in first_item
        assert "explanation" in first_item
