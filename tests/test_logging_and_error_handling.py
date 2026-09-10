import logging
import pytest
import groq
import httpx
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.main import app
from src.core.logging import setup_logging, get_logger

client = TestClient(app)
client_no_raise = TestClient(app, raise_server_exceptions=False)

def test_setup_logging_initialization():
    """Verify logging is configured properly with desired levels and formatters."""
    setup_logging("DEBUG")
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG

    logger = get_logger("test_module")
    assert logger.name == "test_module"

    # Reset back to INFO
    setup_logging("INFO")
    assert logging.getLogger().level == logging.INFO

@patch("src.services.matching_service.matching_service.analyze_skill_gap")
def test_groq_auth_exception_handler_401(mock_analyze):
    """Verify groq.AuthenticationError returns 401 with LLM_AUTHENTICATION_ERROR."""
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_resp = httpx.Response(status_code=401, request=req)
    mock_analyze.side_effect = groq.AuthenticationError("Invalid API Key", response=mock_resp, body={"error": "invalid_api_key"})

    payload = {
        "job_id": "job_auth_err",
        "candidate_id": "cand_auth_err",
        "job_requirements": [{"skill_name": "Python"}],
        "candidate_profile": {"skills": ["Python"]}
    }
    response = client.post("/api/v1/matches/analyze", json=payload)
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "LLM_AUTHENTICATION_ERROR"
    assert "Invalid or expired Groq API key" in body["detail"]

@patch("src.services.matching_service.matching_service.analyze_skill_gap")
def test_groq_rate_limit_exception_handler_429(mock_analyze):
    """Verify groq.RateLimitError returns 429 with LLM_RATE_LIMIT_ERROR."""
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_resp = httpx.Response(status_code=429, request=req)
    mock_analyze.side_effect = groq.RateLimitError("Rate limit exceeded", response=mock_resp, body={"error": "rate_limit"})

    payload = {
        "job_id": "job_rate_err",
        "candidate_id": "cand_rate_err",
        "job_requirements": [{"skill_name": "Python"}],
        "candidate_profile": {"skills": ["Python"]}
    }
    response = client.post("/api/v1/matches/analyze", json=payload)
    assert response.status_code == 429
    body = response.json()
    assert body["error"] == "LLM_RATE_LIMIT_ERROR"
    assert "Groq rate limit exceeded" in body["detail"]

@patch("src.services.matching_service.matching_service.analyze_skill_gap")
def test_groq_gateway_exception_handler_502(mock_analyze):
    """Verify groq.GroqError returns 502 with LLM_GATEWAY_ERROR."""
    mock_analyze.side_effect = groq.GroqError("Connection reset by peer")

    payload = {
        "job_id": "job_gw_err",
        "candidate_id": "cand_gw_err",
        "job_requirements": [{"skill_name": "Python"}],
        "candidate_profile": {"skills": ["Python"]}
    }
    response = client.post("/api/v1/matches/analyze", json=payload)
    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "LLM_GATEWAY_ERROR"
    assert "Connection reset by peer" in body["detail"]

@patch("src.services.matching_service.matching_service.analyze_skill_gap")
def test_unhandled_server_exception_handler_500(mock_analyze):
    """Verify uncaught unexpected exceptions return 500 with INTERNAL_SERVER_ERROR."""
    mock_analyze.side_effect = RuntimeError("Unexpected internal crash")

    payload = {
        "job_id": "job_crash",
        "candidate_id": "cand_crash",
        "job_requirements": [{"skill_name": "Python"}],
        "candidate_profile": {"skills": ["Python"]}
    }
    response = client_no_raise.post("/api/v1/matches/analyze", json=payload)
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "INTERNAL_SERVER_ERROR"
    assert "unexpected internal server error" in body["detail"]
