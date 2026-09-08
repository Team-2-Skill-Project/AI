import os
from pathlib import Path
import pytest
from starlette.testclient import TestClient
from src.api.main import app

client = TestClient(app)


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
    assert "Unsupported file format" in response.json()["detail"]


def test_api_extract_file_image_unsupported_without_ocr():
    response = client.post(
        "/api/v1/cv/extract-file",
        files={"file": ("resume_screenshot.png", b"fake png bytes", "image/png")}
    )
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]
