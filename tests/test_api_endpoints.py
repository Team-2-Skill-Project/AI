from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from src.main import app
from src.schemas.interview import (
    QuestionSetResponse,
    InterviewQuestion,
    AnswerEvaluationResponse
)

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "active_model" in data

@patch("src.services.interview_service.interview_service.create_prep_session")
def test_generate_interview_questions_api(mock_create_prep):
    mock_create_prep.return_value = QuestionSetResponse(
        job_id="job_test_1",
        target_role="Fullstack Developer",
        questions=[
            InterviewQuestion(
                question_id="q_001",
                type="technical",
                question="Explain event loops in Node.js",
                key_points_to_cover=["Call stack", "Callback queue"]
            )
        ]
    )

    payload = {
        "job_id": "job_test_1",
        "target_role": "Fullstack Developer",
        "candidate_id": "cand_001",
        "focus_skills": ["Node.js", "React"],
        "job_summary": "Looking for Node/React fullstack dev.",
        "include_essay": True
    }

    # Pass dynamic header overrides as well
    headers = {
        "X-LLM-Model": "groq/llama-3.1-8b-instant",
        "X-LLM-Temperature": "0.4"
    }

    response = client.post("/api/v1/interview/generate", json=payload, headers=headers)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["job_id"] == "job_test_1"
    assert len(res_data["questions"]) == 1
    assert res_data["questions"][0]["question_id"] == "q_001"

@patch("src.services.interview_service.interview_service.evaluate_submission")
def test_evaluate_interview_answer_api(mock_evaluate):
    mock_evaluate.return_value = AnswerEvaluationResponse(
        question_id="q_001",
        score=8,
        strengths=["Clear logic"],
        improvements=["Add more examples"],
        ideal_answer_outline="Outline steps"
    )

    payload = {
        "question_id": "q_001",
        "question_text": "Explain event loops in Node.js",
        "question_type": "technical",
        "skill_id": "Node.js",
        "user_answer": "Event loop handles asynchronous callbacks."
    }

    response = client.post("/api/v1/interview/evaluate", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["question_id"] == "q_001"
    assert res_data["score"] == 8
