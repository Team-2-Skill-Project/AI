from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from src.main import app
from src.schemas.match import (
    SkillGapAnalysisResponse,
    SkillMatchItem,
    QualificationStatus,
)

client = TestClient(app)

@patch("src.services.matching_service.matching_service.analyze_skill_gap")
def test_matching_api_analyze_endpoint(mock_analyze):
    mock_analyze.return_value = SkillGapAnalysisResponse(
        job_id="job_api_test",
        candidate_id="cand_api_test",
        overall_match_score=87.5,
        qualification_status=QualificationStatus.QUALIFIED,
        full_candidate_summary="Executive summary: Highly qualified candidate.",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Python",
                required_proficiency="Advanced",
                candidate_proficiency="Expert",
                match_score=100.0,
                is_matched=True,
                skill_feedback="Strong match.",
                evidence_found="Years of Python."
            ),
            SkillMatchItem(
                skill_name="Docker",
                required_proficiency="Intermediate",
                candidate_proficiency="Intermediate",
                match_score=75.0,
                is_matched=True,
                skill_feedback="Working knowledge.",
                evidence_found="Dockerized apps."
            )
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=["Explore Kubernetes orchestration."]
    )

    payload = {
        "job_id": "job_api_test",
        "candidate_id": "cand_api_test",
        "job_requirements": [
            {"skill_name": "Python", "proficiency": "Advanced", "is_critical": True},
            {"skill_name": "Docker", "proficiency": "Intermediate", "is_critical": False}
        ],
        "candidate_profile": {
            "candidate_id": "cand_api_test",
            "skills": ["Python", "Docker"],
            "work_history": [
                {
                    "role": "Software Engineer",
                    "company": "Tech Corp",
                    "description": "API engineer"
                }
            ],
            "projects": []
        }
    }

    headers = {
        "X-LLM-Model": "groq/llama-3.1-8b-instant",
        "X-LLM-Temperature": "0.2"
    }

    response = client.post("/api/v1/matches/analyze", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "job_api_test"
    assert data["candidate_id"] == "cand_api_test"
    assert data["overall_match_score"] == 87.5
    assert data["qualification_status"] == "Qualified"
    assert len(data["skill_breakdown"]) == 2
    assert data["skill_breakdown"][0]["is_matched"] is True
    assert data["missing_critical_skills"] == []
    assert len(data["recommended_upskilling_path"]) == 1

def test_matching_api_validation_error():
    # Missing required job_id and candidate_id
    invalid_payload = {
        "job_requirements": []
    }
    response = client.post("/api/v1/matches/analyze", json=invalid_payload)
    assert response.status_code == 422


@patch("src.services.matching_service.matching_service.analyze_skill_gap")
def test_matching_api_skill_gap_endpoint(mock_analyze):
    mock_analyze.return_value = SkillGapAnalysisResponse(
        job_id="job_gap_test",
        candidate_id="cand_gap_test",
        overall_match_score=60.0,
        qualification_status=QualificationStatus.PARTIALLY_QUALIFIED,
        full_candidate_summary="Partially qualified candidate summary.",
        skill_breakdown=[],
        missing_critical_skills=["Kubernetes"],
        recommended_upskilling_path=["Learn Kubernetes"]
    )
    payload = {
        "job_id": "job_gap_test",
        "candidate_id": "cand_gap_test",
        "job_requirements": ["Kubernetes"],
        "candidate_profile": {"candidate_id": "cand_gap_test", "skills": []}
    }
    response = client.post("/api/v1/matches/skill-gap", json=payload)
    assert response.status_code == 200
    assert response.json()["qualification_status"] == "Partially Qualified"


@patch("src.services.matching_service.matching_service.analyze_skill_gap")
def test_matching_api_explain_endpoint(mock_analyze):
    mock_analyze.return_value = SkillGapAnalysisResponse(
        job_id="job_exp_test",
        candidate_id="cand_exp_test",
        overall_match_score=92.0,
        qualification_status=QualificationStatus.QUALIFIED,
        full_candidate_summary="Candidate demonstrates deep proficiency.",
        skill_breakdown=[],
        missing_critical_skills=[],
        recommended_upskilling_path=[]
    )
    payload = {
        "job_id": "job_exp_test",
        "candidate_id": "cand_exp_test",
        "job_requirements": ["Python"],
        "candidate_profile": {"candidate_id": "cand_exp_test", "skills": ["Python"]}
    }
    response = client.post("/api/v1/matches/explain", json=payload)
    assert response.status_code == 200
    assert response.json()["full_candidate_summary"] == "Candidate demonstrates deep proficiency."

    # Now verify retrieving persisted explanation
    resp_get = client.get("/api/v1/matches/job_exp_test/candidate/cand_exp_test")
    assert resp_get.status_code == 200
    assert resp_get.json()["job_id"] == "job_exp_test"
    assert resp_get.json()["overall_match_score"] == 92.0
