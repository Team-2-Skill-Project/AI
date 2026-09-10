from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from src.api.main import app
from src.api.schemas.cv_schemas import ExtractionErrorResponse
from src.core.llm_service import LLMService

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_llm_provider():
    """Ensure no test in test_api_cv makes real network calls to external LLM providers."""
    with patch.object(LLMService, "is_available", return_value=False), \
         patch.object(LLMService, "generate_json", side_effect=RuntimeError("No live network calls allowed in unit tests")):
        yield



def test_api_root_and_health():
    # Root
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert resp_root.json()["docs"] == "/docs"

    # Health
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] == "healthy"


def test_api_extract_file_valid():
    sample_path = Path(__file__).parent / "samples" / "sample_ahmed_hassan_cv.txt"
    assert sample_path.exists()

    with open(sample_path, "rb") as f:
        response = client.post(
            "/api/v1/cv/extract-file",
            files={"file": ("sample_ahmed_hassan_cv.txt", f, "text/plain")},
            data={"candidate_id": "cand_test_file_001"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["candidate_id"] == "cand_test_file_001"
    assert data["profile"]["name"] == "Ahmed Hassan"
    assert data["profile"]["email"] == "ahmed.hassan@example.com"

    # Verify skills with evidence & confidence
    skills = {s["skill_id"]: s for s in data["skills"]}
    assert "skill_python" in skills
    assert skills["skill_python"]["confidence"] >= 0.85
    assert len(skills["skill_python"]["evidence"]) > 0


def test_api_extract_file_unsupported_format():
    response = client.post(
        "/api/v1/cv/extract-file",
        files={"file": ("malicious.exe", b"binary content", "application/octet-stream")}
    )
    assert response.status_code == 400
    data = response.json()
    error_schema = ExtractionErrorResponse.model_validate(data)
    assert "Unsupported file format" in error_schema.detail
    assert error_schema.error_code == "UNSUPPORTED_FILE_TYPE"


def test_api_extract_file_legacy_doc_rejected_with_guidance():
    """Legacy .doc format must be cleanly rejected with guidance to convert to .docx or .pdf."""
    response = client.post(
        "/api/v1/cv/extract-file",
        files={"file": ("my_resume.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 legacy doc content", "application/msword")}
    )
    assert response.status_code == 400
    data = response.json()
    error_schema = ExtractionErrorResponse.model_validate(data)
    assert "Legacy '.doc' format is not supported" in error_schema.detail
    assert ".docx" in error_schema.detail
    assert error_schema.error_code == "UNSUPPORTED_FILE_TYPE"


def test_api_extract_file_image_unsupported_without_ocr():
    response = client.post(
        "/api/v1/cv/extract-file",
        files={"file": ("resume_screenshot.png", b"fake png bytes", "image/png")}
    )
    assert response.status_code == 400
    data = response.json()
    error_schema = ExtractionErrorResponse.model_validate(data)
    assert "Unsupported file format" in error_schema.detail
    assert error_schema.error_code == "UNSUPPORTED_FILE_TYPE"


def test_api_extract_file_path_traversal_prevention():
    """Path traversal filename (relative or absolute Windows path) must not escape temp dir or overwrite files."""
    test_content = b"John Safe\nEmail: john.safe@example.com\nSKILLS\nPython\n"

    # Test relative path traversal
    response = client.post(
        "/api/v1/cv/extract-file",
        files={"file": ("../../etc/passwd.txt", test_content, "text/plain")},
        data={"candidate_id": "cand_sec_001"}
    )
    assert response.status_code == 200
    assert response.json()["profile"]["name"] == "John Safe"

    # Test Windows absolute path traversal attempt
    response_win = client.post(
        "/api/v1/cv/extract-file",
        files={"file": (r"C:\Windows\System32\target.txt", test_content, "text/plain")},
        data={"candidate_id": "cand_sec_002"}
    )
    assert response_win.status_code == 200
    assert response_win.json()["profile"]["name"] == "John Safe"


def test_api_extract_file_empty_rejected():
    """Empty files (0 bytes) must be rejected with 400 Bad Request matching ExtractionErrorResponse schema."""
    response = client.post(
        "/api/v1/cv/extract-file",
        files={"file": ("empty.txt", b"", "text/plain")}
    )
    assert response.status_code == 400
    data = response.json()
    error_schema = ExtractionErrorResponse.model_validate(data)
    assert "empty" in error_schema.detail.lower()
    assert error_schema.error_code == "EMPTY_FILE"


def test_api_extract_file_oversized_rejected():
    """Files exceeding maximum allowed upload size must be rejected with 413 matching ExtractionErrorResponse schema."""
    # 11 MB payload (exceeds 10 MB limit)
    large_content = b"A" * (11 * 1024 * 1024)
    response = client.post(
        "/api/v1/cv/extract-file",
        files={"file": ("huge_cv.txt", large_content, "text/plain")}
    )
    assert response.status_code == 413
    data = response.json()
    error_schema = ExtractionErrorResponse.model_validate(data)
    assert "exceeds maximum allowed limit" in error_schema.detail
    assert error_schema.error_code == "FILE_TOO_LARGE"


def test_api_extract_file_async_and_poll_status():
    """README.md:66 requirement: Non-trivial extraction runs as async background job with pollable status."""
    sample_path = Path(__file__).parent / "samples" / "sample_ahmed_hassan_cv.txt"
    assert sample_path.exists()

    with open(sample_path, "rb") as f:
        # Submit async job
        response = client.post(
            "/api/v1/cv/extract-file-async",
            files={"file": ("sample_ahmed_hassan_cv.txt", f, "text/plain")},
            data={"candidate_id": "cand_async_001"}
        )

    assert response.status_code == 202
    job_data = response.json()
    assert "job_id" in job_data
    assert job_data["status"] in ("queued", "processing", "completed")

    job_id = job_data["job_id"]

    # Poll status
    poll_response = client.get(f"/api/v1/cv/jobs/{job_id}")
    assert poll_response.status_code == 200
    poll_data = poll_response.json()
    assert poll_data["job_id"] == job_id
    assert poll_data["status"] == "completed"
    assert poll_data["result"] is not None
    assert poll_data["result"]["profile"]["name"] == "Ahmed Hassan"


def test_api_get_job_status_not_found():
    """Polling a non-existent job ID returns 404 with ExtractionErrorResponse format."""
    response = client.get("/api/v1/cv/jobs/job_cv_non_existent")
    assert response.status_code == 404
    data = response.json()
    error_schema = ExtractionErrorResponse.model_validate(data)
    assert "not found" in error_schema.detail.lower()
    assert error_schema.error_code == "JOB_NOT_FOUND"


def test_cors_preflight_and_headers():
    """P2 Test: CORS must allow specific configured origins and methods while preserving security."""
    response = client.options(
        "/api/v1/cv/extract-file",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,Authorization"
        }
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_rate_limiting_enforcement(monkeypatch):
    """P2 Test: Exceeding request quota triggers 429 Too Many Requests with ExtractionErrorResponse."""
    from src.api.security import rate_limiter
    from src.core.config import get_app_settings

    rate_limiter.reset()

    # Configure low rate limit for testing
    settings = get_app_settings()
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "enable_rate_limiting", True)

    # Make 3 allowed requests
    for _ in range(3):
        resp = client.get("/api/v1/cv/jobs/test_job_rate")
        assert resp.status_code == 404  # Reaches endpoint

    # 4th request must hit rate limit (429)
    resp_blocked = client.get("/api/v1/cv/jobs/test_job_rate")
    assert resp_blocked.status_code == 429
    data = resp_blocked.json()
    error_schema = ExtractionErrorResponse.model_validate(data)
    assert "rate limit exceeded" in error_schema.detail.lower()
    assert error_schema.error_code == "RATE_LIMIT_EXCEEDED"
    assert "retry-after" in resp_blocked.headers

    rate_limiter.reset()


def test_api_key_authentication(monkeypatch):
    """P2 Test: When API key authentication is enabled, missing/invalid keys return 401."""
    from src.core.config import get_app_settings

    settings = get_app_settings()
    monkeypatch.setattr(settings, "enable_api_key_auth", True)
    monkeypatch.setattr(settings, "api_key", "secret-test-key-12345")

    # 1. Request without key -> 401
    resp_no_key = client.get("/api/v1/cv/jobs/test_job")
    assert resp_no_key.status_code == 401
    data = resp_no_key.json()
    error_schema = ExtractionErrorResponse.model_validate(data)
    assert error_schema.error_code == "UNAUTHORIZED"

    # 2. Request with invalid key -> 401
    resp_wrong_key = client.get("/api/v1/cv/jobs/test_job", headers={"X-API-Key": "wrong-key"})
    assert resp_wrong_key.status_code == 401

    # 3. Request with valid X-API-Key -> 404 (authorized, reaches endpoint)
    resp_valid_header = client.get("/api/v1/cv/jobs/test_job", headers={"X-API-Key": "secret-test-key-12345"})
    assert resp_valid_header.status_code == 404

    # 4. Request with valid Bearer token -> 404 (authorized)
    resp_valid_bearer = client.get("/api/v1/cv/jobs/test_job", headers={"Authorization": "Bearer secret-test-key-12345"})
    assert resp_valid_bearer.status_code == 404

