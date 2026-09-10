import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.main import app as fastapi_app
from src.db.base import Base, get_db
from src.services.review_queue_service import review_queue_service
from src.schemas.match import SkillGapAnalysisResponse, SkillMatchItem, QualificationStatus
from src.schemas.interview import AnswerEvaluationResponse, SecurityAssessment
from src.schemas.review_queue import ReviewResolutionRequest

from sqlalchemy.pool import StaticPool
from src.db.models.review_queue import ReviewQueueModel
from src.db.models.match import MatchRecordModel
from src.db.models.interview import InterviewSessionModel

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False
)
Base.metadata.create_all(bind=engine)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

fastapi_app.dependency_overrides[get_db] = override_get_db
client = TestClient(fastapi_app)

def test_should_flag_match_criteria():
    # Borderline score & Partially Qualified
    match_partially = SkillGapAnalysisResponse(
        job_id="job_rev_1",
        candidate_id="cand_rev_1",
        overall_match_score=68.5,
        qualification_status=QualificationStatus.PARTIALLY_QUALIFIED,
        full_candidate_summary="Needs upskilling.",
        skill_breakdown=[],
        missing_critical_skills=["Kubernetes"],
        recommended_upskilling_path=[]
    )
    needs_review, reasons, priority = review_queue_service.should_flag_match(match_partially)
    assert needs_review is True
    assert priority in ("high", "urgent")
    assert any("Borderline" in r for r in reasons)

    # Qualified with 100% score and 0 missing critical skills
    match_perfect = SkillGapAnalysisResponse(
        job_id="job_rev_2",
        candidate_id="cand_rev_2",
        overall_match_score=95.0,
        qualification_status=QualificationStatus.QUALIFIED,
        full_candidate_summary="Outstanding candidate.",
        skill_breakdown=[],
        missing_critical_skills=[],
        recommended_upskilling_path=[]
    )
    needs_review, reasons, priority = review_queue_service.should_flag_match(match_perfect)
    assert needs_review is False

def test_should_flag_interview_security_risk():
    eval_insecure = AnswerEvaluationResponse(
        question_id="q_sec_1",
        score=4,
        strengths=[],
        improvements=["Do not concatenate user input directly into SQL queries."],
        ideal_answer_outline="Use parameterized queries.",
        security_assessment=SecurityAssessment(
            has_security_vulnerabilities=True,
            identified_risks=["SQL Injection risk via string formatting"],
            security_score=3,
            mitigation_suggestions=["Adopt SQLAlchemy ORM or parameterized queries."]
        )
    )
    needs_review, reasons, priority = review_queue_service.should_flag_interview(eval_insecure)
    assert needs_review is True
    assert priority == "urgent"
    assert any("vulnerabilities" in r for r in reasons)

def test_review_queue_api_workflow():
    db = TestingSessionLocal()

    # Enqueue an item directly through service
    match_item = SkillGapAnalysisResponse(
        job_id="job_api_q1",
        candidate_id="cand_api_q1",
        overall_match_score=60.0,
        qualification_status=QualificationStatus.PARTIALLY_QUALIFIED,
        full_candidate_summary="Borderline candidate.",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Python",
                required_proficiency="Advanced",
                candidate_proficiency="Intermediate",
                match_score=75.0,
                is_matched=True,
                skill_feedback="Moderate.",
                evidence_found="Small projects."
            )
        ],
        missing_critical_skills=["AWS"],
        recommended_upskilling_path=["AWS Certified Solutions Architect"]
    )
    enqueued = review_queue_service.enqueue_match_if_needed(match_item, db=db, force=True)
    assert enqueued is not None
    item_id = enqueued.id
    db.close()

    # 1. List queue items
    response = client.get("/api/v1/review-queue/?status=pending")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(i["id"] == item_id for i in data["items"])

    # 2. Get single item
    response = client.get(f"/api/v1/review-queue/{item_id}")
    assert response.status_code == 200
    assert response.json()["id"] == item_id

    # 3. Claim item
    response = client.post(
        f"/api/v1/review-queue/{item_id}/claim",
        json={"reviewer_id": "recruiter_dave"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_review"
    assert response.json()["reviewer_id"] == "recruiter_dave"

    # 4. Resolve item
    response = client.post(
        f"/api/v1/review-queue/{item_id}/resolve",
        json={
            "status": "approved",
            "reviewer_id": "recruiter_dave",
            "reviewer_notes": "Candidate has equivalent GCP experience, approved for interview.",
            "adjusted_qualification_status": "Qualified",
            "adjusted_score": 78.0
        }
    )
    assert response.status_code == 200
    resolved_data = response.json()
    assert resolved_data["status"] == "approved"
    assert resolved_data["resolution"]["adjusted_score"] == 78.0
