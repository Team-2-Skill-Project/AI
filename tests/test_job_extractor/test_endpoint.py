"""
Integration tests for POST /api/v1/jobs/analyze endpoint.

Tests auth, validation, and the full request-response cycle (LLM mocked).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from src.api.main import app
from src.api.dependencies import get_job_pipeline
from src.job_extractor.pipeline import JobExtractionPipeline
from src.taxonomy.taxonomy_manager import TaxonomyManager

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "job_descriptions"
BACKEND_ENGINEER_JD = (FIXTURES_DIR / "jd_senior_backend_engineer.txt").read_text(encoding="utf-8")
VAGUE_ANALYST_JD = (FIXTURES_DIR / "jd_data_analyst_vague.txt").read_text(encoding="utf-8")

client = TestClient(app)

VALID_API_KEY = "test-secret-key-job"


def _mock_rich_llm_response() -> dict:
    return {
        "role_family": "Engineering",
        "seniority": "Senior",
        "canonical_role": "Backend Software Engineer",
        "required_skills": [
            {"name": "Python", "importance": "critical", "required_level": "advanced"},
            {"name": "FastAPI", "importance": "critical", "required_level": None},
            {"name": "PostgreSQL", "importance": "critical", "required_level": "advanced"},
            {"name": "Redis", "importance": "critical", "required_level": None},
        ],
        "preferred_skills": [
            {"name": "Kubernetes", "importance": "nice_to_have", "required_level": None},
        ],
        "responsibilities": [
            "Design and implement high-performance backend APIs",
            "Lead code reviews",
        ],
        "min_years_experience": 5,
        "max_years_experience": 8,
        "constraints": ["Remote-first with optional Cairo office"],
    }


def _mock_vague_llm_response() -> dict:
    return {
        "role_family": None,
        "seniority": None,
        "canonical_role": "Data Analyst",
        "required_skills": [
            {"name": "SQL", "importance": "important", "required_level": None},
            {"name": "Tableau", "importance": "important", "required_level": None},
        ],
        "preferred_skills": [],
        "responsibilities": ["Analyze datasets", "Build dashboards"],
        "min_years_experience": None,
        "max_years_experience": None,
        "constraints": [],
    }


def _build_mock_pipeline(llm_response: dict) -> JobExtractionPipeline:
    """Build a real pipeline with a mocked LLM service."""
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    mock_llm.generate_json.return_value = llm_response
    taxonomy = TaxonomyManager()
    pipeline = JobExtractionPipeline(taxonomy_manager=taxonomy)
    pipeline.extractor.llm = mock_llm
    return pipeline


# ── Auth tests ────────────────────────────────────────────────────────────────
# Note: API key auth is disabled by default (enable_api_key_auth=False).
# These tests use monkeypatch to enable it temporarily, matching the pattern in test_api_cv.py.

class TestJobEndpointAuth:
    def test_missing_api_key_returns_401_when_auth_enabled(self, monkeypatch):
        from src.core.config import get_app_settings
        settings = get_app_settings()
        monkeypatch.setattr(settings, "enable_api_key_auth", True)
        monkeypatch.setattr(settings, "api_key", VALID_API_KEY)

        response = client.post(
            "/api/v1/jobs/analyze",
            json={"job_description": BACKEND_ENGINEER_JD},
        )
        assert response.status_code == 401

    def test_invalid_api_key_returns_401_when_auth_enabled(self, monkeypatch):
        from src.core.config import get_app_settings
        settings = get_app_settings()
        monkeypatch.setattr(settings, "enable_api_key_auth", True)
        monkeypatch.setattr(settings, "api_key", VALID_API_KEY)

        response = client.post(
            "/api/v1/jobs/analyze",
            headers={"X-API-Key": "wrong-key"},
            json={"job_description": BACKEND_ENGINEER_JD},
        )
        assert response.status_code == 401


# ── Validation tests ──────────────────────────────────────────────────────────

class TestJobEndpointValidation:
    def test_short_job_description_returns_422(self):
        """job_description < 50 chars must fail Pydantic validation."""
        response = client.post(
            "/api/v1/jobs/analyze",
            json={"job_description": "Too short."},
        )
        assert response.status_code == 422

    def test_missing_job_description_returns_422(self):
        response = client.post(
            "/api/v1/jobs/analyze",
            json={},
        )
        assert response.status_code == 422


# ── Happy path tests ──────────────────────────────────────────────────────────

class TestJobEndpointHappyPath:
    def test_full_extraction_returns_200(self):
        mock_pipeline = _build_mock_pipeline(_mock_rich_llm_response())
        app.dependency_overrides[get_job_pipeline] = lambda: mock_pipeline

        try:
            response = client.post(
                "/api/v1/jobs/analyze",
                json={"job_description": BACKEND_ENGINEER_JD},
            )
            assert response.status_code == 200
            data = response.json()

            # Top-level fields
            assert data["job_id"] is None
            assert data["persisted"] is False
            profile = data["profile"]

            assert profile["role_family"] == "Engineering"
            assert profile["seniority"] == "Senior"
            assert profile["canonical_role"] == "Backend Software Engineer"
            assert len(profile["required_skills"]) >= 1
            assert len(profile["responsibilities"]) >= 1
            assert 0.0 <= profile["extraction_confidence"] <= 1.0
        finally:
            app.dependency_overrides.pop(get_job_pipeline, None)

    def test_null_seniority_preserved_in_response(self):
        """Vague JD must return seniority=null in the API response."""
        mock_pipeline = _build_mock_pipeline(_mock_vague_llm_response())
        app.dependency_overrides[get_job_pipeline] = lambda: mock_pipeline

        try:
            response = client.post(
                "/api/v1/jobs/analyze",
                json={"job_description": VAGUE_ANALYST_JD},
            )
            assert response.status_code == 200
            profile = response.json()["profile"]
            assert profile["role_family"] is None
            assert profile["seniority"] is None
        finally:
            app.dependency_overrides.pop(get_job_pipeline, None)

    def test_required_skills_have_expected_structure(self):
        mock_pipeline = _build_mock_pipeline(_mock_rich_llm_response())
        app.dependency_overrides[get_job_pipeline] = lambda: mock_pipeline

        try:
            response = client.post(
                "/api/v1/jobs/analyze",
                json={"job_description": BACKEND_ENGINEER_JD},
            )
            assert response.status_code == 200
            skills = response.json()["profile"]["required_skills"]
            for skill in skills:
                assert "canonical_name" in skill
                assert "raw_extracted" in skill
                assert "importance" in skill
                assert skill["importance"] in ("critical", "important", "nice_to_have")
        finally:
            app.dependency_overrides.pop(get_job_pipeline, None)

    def test_with_job_id_sets_persisted_false_when_not_in_db(self):
        """
        When job_id is provided but not found in DB, persisted must be False
        and the response must still be 200 (DB failure is non-fatal).
        """
        mock_pipeline = _build_mock_pipeline(_mock_rich_llm_response())
        app.dependency_overrides[get_job_pipeline] = lambda: mock_pipeline

        try:
            with patch(
                "src.api.routers.job_router.JobRequirementRepository.upsert",
                return_value=False,
            ):
                response = client.post(
                    "/api/v1/jobs/analyze",
                    json={
                        "job_description": BACKEND_ENGINEER_JD,
                        "job_id": "550e8400-e29b-41d4-a716-446655440000",
                    },
                )
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert data["persisted"] is False
        finally:
            app.dependency_overrides.pop(get_job_pipeline, None)


# ── Health check ──────────────────────────────────────────────────────────────

class TestHealthIncludesJobFeature:
    def test_health_reports_job_description_understanding_active(self):
        response = client.get("/health")
        assert response.status_code == 200
        features = response.json().get("features", {})
        assert features.get("job_description_understanding") == "active"
