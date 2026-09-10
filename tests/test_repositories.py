import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.base import Base
from src.db.repositories.match_repository import MatchRepository
from src.db.repositories.review_queue_repository import ReviewQueueRepository
from src.db.repositories.interview_repository import InterviewRepository
from src.schemas.match import SkillGapAnalysisResponse, SkillMatchItem, QualificationStatus
from src.schemas.interview import QuestionSetResponse, InterviewQuestion, AnswerEvaluationResponse, SecurityAssessment

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_match_repository_crud(test_db):
    repo = MatchRepository(test_db)

    match_res = SkillGapAnalysisResponse(
        job_id="job_repo_01",
        candidate_id="cand_repo_01",
        overall_match_score=84.5,
        qualification_status=QualificationStatus.QUALIFIED,
        full_candidate_summary="Strong backend engineer.",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Python",
                required_proficiency="Advanced",
                candidate_proficiency="Expert",
                match_score=100.0,
                is_matched=True,
                skill_feedback="Strong experience.",
                evidence_found="5 years Python."
            )
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=["Explore Rust."]
    )

    # Save
    record = repo.save_match_result(match_res)
    assert record.id is not None
    assert record.job_id == "job_repo_01"

    # Get latest
    latest = repo.get_latest_match("job_repo_01", "cand_repo_01")
    assert latest is not None
    assert latest.overall_match_score == 84.5
    dict_repr = latest.to_dict()
    assert dict_repr["overall_match_score"] == 84.5
    assert len(dict_repr["skill_breakdown"]) == 1

    # List by job
    job_records = repo.list_by_job("job_repo_01")
    assert len(job_records) == 1

def test_review_queue_repository_lifecycle(test_db):
    repo = ReviewQueueRepository(test_db)

    # Enqueue
    item = repo.enqueue(
        item_type="match_analysis",
        target_id="job_01:cand_01",
        payload={"score": 68.0, "status": "Partially Qualified"},
        flagged_reasons=["Borderline score"],
        priority="high"
    )
    assert item.id is not None
    assert item.status == "pending"
    assert item.priority == "high"

    # List items
    pending_items = repo.list_items(status="pending")
    assert len(pending_items) == 1

    # Claim item
    claimed = repo.claim_item(item.id, reviewer_id="recruiter_sarah")
    assert claimed.status == "in_review"
    assert claimed.reviewer_id == "recruiter_sarah"

    # Resolve item
    resolved = repo.resolve_item(
        item_id=item.id,
        status="approved",
        reviewer_notes="Candidate approved based on adjacent project work.",
        resolution={"adjusted_status": "Qualified"}
    )
    assert resolved.status == "approved"
    assert resolved.reviewer_notes == "Candidate approved based on adjacent project work."
    assert resolved.reviewed_at is not None

def test_interview_repository(test_db):
    repo = InterviewRepository(test_db)

    # Save session
    session_res = QuestionSetResponse(
        job_id="job_interview_01",
        target_role="Fullstack Lead",
        questions=[
            InterviewQuestion(
                question_id="q_100",
                type="technical",
                question="Explain React reconciliation.",
                key_points_to_cover=["Virtual DOM", "Diffing algorithm"]
            )
        ]
    )
    session_record = repo.save_session(session_res, candidate_id="cand_test_01")
    assert session_record.id is not None
    assert session_record.job_id == "job_interview_01"

    # Save answer evaluation
    eval_res = AnswerEvaluationResponse(
        question_id="q_100",
        score=9,
        strengths=["Clear concise explanation."],
        improvements=[],
        ideal_answer_outline="Mention fiber tree.",
        security_assessment=SecurityAssessment(
            has_security_vulnerabilities=False,
            identified_risks=[],
            security_score=10,
            mitigation_suggestions=[]
        )
    )
    eval_record = repo.save_answer_evaluation(eval_res, session_id=session_record.id)
    assert eval_record.id is not None
    assert eval_record.score == 9
