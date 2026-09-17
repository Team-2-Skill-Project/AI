from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
# pyrefly: ignore [missing-import]
from src.api.main import app
# pyrefly: ignore [missing-import]
from src.core.config import get_app_settings

client = TestClient(app)
app_settings = get_app_settings()

API_KEY_HEADER = {"X-API-Key": app_settings.api_key} if app_settings.api_key else {}


def test_generate_and_get_roadmap_endpoint():
    # 1. Generate Roadmap
    payload = {
        "candidate_id": "cand_api_201",
        "target_role": "DevOps Lead",
        "role_family": "Engineering",
        "skill_gaps": ["Terraform", "Ansible"],
    }
    response = client.post("/api/v1/roadmap/generate", json=payload, headers=API_KEY_HEADER)
    assert response.status_code == 200
    data = response.json()
    assert data["candidate_id"] == "cand_api_201"
    assert data["target_role"] == "DevOps Lead"
    assert len(data["phases"]) == 2

    # 2. GET Roadmap
    get_res = client.get("/api/v1/roadmap/cand_api_201", headers=API_KEY_HEADER)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["candidate_id"] == "cand_api_201"

    # 3. Update Task Status
    task_id = get_data["phases"][0]["milestones"][0]["tasks"][0]["task_id"]
    complete_res = client.post(
        f"/api/v1/roadmap/tasks/{task_id}/complete",
        json={"candidate_id": "cand_api_201", "task_id": task_id, "status": "completed"},
        headers=API_KEY_HEADER,
    )
    assert complete_res.status_code == 200
    updated_data = complete_res.json()
    assert updated_data["phases"][0]["milestones"][0]["tasks"][0]["status"] == "completed"

    # 4. Refresh Roadmap
    refresh_res = client.post(
        "/api/v1/roadmap/refresh",
        json={
            "candidate_id": "cand_api_201",
            "new_skill_gaps": ["Kubernetes Security"],
        },
        headers=API_KEY_HEADER,
    )
    assert refresh_res.status_code == 200
    refreshed_data = refresh_res.json()
    assert refreshed_data["candidate_id"] == "cand_api_201"
