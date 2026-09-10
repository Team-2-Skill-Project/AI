import pytest
from unittest.mock import AsyncMock, MagicMock
from src.schemas.interview import (
    QuestionGenerationRequest,
    AnswerSubmission,
    QuestionSetResponse,
    InterviewQuestion,
    AnswerEvaluationResponse
)
from src.services.interview_service import InterviewService

def test_schemas_validation():
    # QuestionGenerationRequest with custom job_summary
    req = QuestionGenerationRequest(
        job_id="job_123",
        target_role="Frontend Engineer",
        candidate_id="cand_456",
        focus_skills=["React", "TypeScript"],
        job_summary="Build scalable React apps with TypeScript."
    )
    assert req.job_summary == "Build scalable React apps with TypeScript."

    # AnswerSubmission with question_type
    sub = AnswerSubmission(
        question_id="q_1",
        question_text="Explain React hooks",
        question_type="technical",
        skill_id="React",
        user_answer="Hooks allow state in functional components."
    )
    assert sub.question_type == "technical"

@pytest.mark.asyncio
async def test_interview_service_dynamic_job_summary():
    mock_chains = MagicMock()
    mock_chains.generate_questions = AsyncMock(return_value=QuestionSetResponse(
        job_id="job_1",
        target_role="Data Engineer",
        questions=[
            InterviewQuestion(
                question_id="q_1",
                type="technical",
                question="Explain MapReduce",
                key_points_to_cover=["Map", "Reduce"]
            )
        ]
    ))

    service = InterviewService(chains=mock_chains)

    # When job_summary is not provided, service builds dynamic contextual summary
    req = QuestionGenerationRequest(
        job_id="job_1",
        target_role="Data Engineer",
        candidate_id="cand_1",
        focus_skills=["Spark", "Kafka"]
    )
    res = await service.create_prep_session(req)

    assert res.job_id == "job_1"
    assert len(res.questions) == 1

    # Check what was passed to generate_questions
    call_args = mock_chains.generate_questions.call_args[1]
    assert "Data Engineer" in call_args["job_summary"]
    assert "Spark, Kafka" in call_args["job_summary"]
    # Ensure it's not the hardcoded Python/FastAPI summary
    assert "Requires Python, FastAPI, secure JWT" not in call_args["job_summary"]

@pytest.mark.asyncio
async def test_interview_service_explicit_job_summary():
    mock_chains = MagicMock()
    mock_chains.generate_questions = AsyncMock(return_value=QuestionSetResponse(
        job_id="job_2",
        target_role="Security Analyst",
        questions=[]
    ))

    service = InterviewService(chains=mock_chains)

    req = QuestionGenerationRequest(
        job_id="job_2",
        target_role="Security Analyst",
        candidate_id="cand_2",
        job_summary="Analyze threat intelligence and SIEM logs."
    )
    await service.create_prep_session(req)

    call_args = mock_chains.generate_questions.call_args[1]
    assert call_args["job_summary"] == "Analyze threat intelligence and SIEM logs."

@pytest.mark.asyncio
async def test_interview_service_evaluate_submission():
    mock_chains = MagicMock()
    mock_chains.evaluate_answer = AsyncMock(return_value=AnswerEvaluationResponse(
        question_id="q_1",
        score=9,
        strengths=["Clear explanation"],
        improvements=[],
        ideal_answer_outline="Mention state hooks."
    ))

    service = InterviewService(chains=mock_chains)

    sub = AnswerSubmission(
        question_id="q_1",
        question_text="What is React?",
        question_type="technical",
        skill_id="React",
        user_answer="A UI library."
    )
    res = await service.evaluate_submission(sub)

    assert res.score == 9
    call_args = mock_chains.evaluate_answer.call_args[1]
    assert call_args["question_type"] == "technical"
