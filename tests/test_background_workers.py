import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.workers.dispatcher import task_dispatcher
from src.workers.tasks import async_analyze_skill_gap, async_generate_interview_questions, async_evaluate_interview_answer
from src.schemas.match import SkillGapAnalysisResponse, SkillMatchItem, QualificationStatus
from src.schemas.interview import QuestionSetResponse, InterviewQuestion, AnswerEvaluationResponse

@patch("src.workers.tasks.matching_service.analyze_skill_gap")
def test_async_analyze_skill_gap_execution(mock_analyze):
    mock_analyze.return_value = SkillGapAnalysisResponse(
        job_id="job_worker_01",
        candidate_id="cand_worker_01",
        overall_match_score=90.0,
        qualification_status=QualificationStatus.QUALIFIED,
        full_candidate_summary="Top tier candidate.",
        skill_breakdown=[
            SkillMatchItem(
                skill_name="Python",
                required_proficiency="Advanced",
                candidate_proficiency="Expert",
                match_score=100.0,
                is_matched=True,
                skill_feedback="Superb.",
                evidence_found="Extensive experience."
            )
        ],
        missing_critical_skills=[],
        recommended_upskilling_path=[]
    )

    payload = {
        "job_id": "job_worker_01",
        "candidate_id": "cand_worker_01",
        "job_requirements": [{"skill_name": "Python"}],
        "candidate_profile": {"skills": ["Python"]}
    }

    result = async_analyze_skill_gap(payload, auto_persist=False, auto_enqueue_review=False)
    assert result["job_id"] == "job_worker_01"
    assert result["overall_match_score"] == 90.0
    assert result["qualification_status"] == "Qualified"

@patch("src.workers.tasks.interview_service.create_prep_session")
def test_async_generate_interview_questions_execution(mock_prep):
    mock_prep.return_value = QuestionSetResponse(
        job_id="job_prep_01",
        target_role="Backend Engineer",
        questions=[
            InterviewQuestion(
                question_id="q_1",
                type="technical",
                question="Explain ACID properties.",
                key_points_to_cover=["Atomicity", "Consistency", "Isolation", "Durability"]
            )
        ]
    )

    payload = {
        "job_id": "job_prep_01",
        "target_role": "Backend Engineer",
        "candidate_id": "cand_01",
        "focus_skills": ["Databases"]
    }

    result = async_generate_interview_questions(payload, auto_persist=False)
    assert result["job_id"] == "job_prep_01"
    assert len(result["questions"]) == 1

def test_task_dispatcher_sync_fallback():
    with patch("src.workers.dispatcher.async_analyze_skill_gap") as mock_task:
        mock_task.return_value = {"job_id": "job_01", "overall_match_score": 85.0}

        # Dispatch with use_celery=False to test direct execution
        dispatch_res = task_dispatcher.dispatch_skill_gap_analysis(
            payload={"job_id": "job_01"},
            use_celery=False
        )
        assert dispatch_res["status"] == "completed"
        assert dispatch_res["mode"] == "sync"
        assert dispatch_res["result"]["job_id"] == "job_01"
