"""
Unit tests for JobRequirementRepository.

DB interactions are mocked — no real DB connection required.
"""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.job_extractor.models import JobRequirementProfile, NormalizedSkill
from src.db.repositories.job_requirement_repository import JobRequirementRepository


def _make_profile(**kwargs) -> JobRequirementProfile:
    defaults = dict(
        role_family="Engineering",
        seniority="Senior",
        canonical_role="Backend Software Engineer",
        required_skills=[
            NormalizedSkill(
                skill_id="skill_python",
                canonical_name="Python",
                category="Programming Languages",
                raw_extracted="Python",
                importance="critical",
                required_level="advanced",
            )
        ],
        preferred_skills=[],
        responsibilities=["Design APIs", "Lead code reviews"],
        min_years_experience=5,
        max_years_experience=8,
        constraints=["Remote from Egypt only"],
        extraction_confidence=0.90,
    )
    defaults.update(kwargs)
    return JobRequirementProfile(**defaults)


# ── Tests: upsert returns False when job_id not found ────────────────────────

class TestJobRequirementRepositoryUpsert:
    def test_upsert_returns_false_when_job_not_in_db(self):
        """If job_id is not found in the DB, upsert() must return False without raising."""
        repo = JobRequirementRepository()
        profile = _make_profile()

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch("src.db.repositories.job_requirement_repository.SessionLocal", return_value=mock_session):
            result = repo.upsert(job_id="nonexistent-uuid", profile=profile)

        assert result is False
        mock_session.commit.assert_not_called()
        mock_session.close.assert_called_once()

    def test_upsert_returns_true_and_commits_when_job_found(self):
        """If job_id is found, upsert() must update fields and return True."""
        repo = JobRequirementRepository()
        profile = _make_profile()

        mock_record = MagicMock()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_record

        with patch("src.db.repositories.job_requirement_repository.SessionLocal", return_value=mock_session):
            result = repo.upsert(job_id="valid-uuid", profile=profile)

        assert result is True
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()

        # Verify the fields were assigned
        assert mock_record.canonical_role == "Backend Software Engineer"
        assert mock_record.min_years_experience == 5
        assert mock_record.max_years_experience == 8
        assert mock_record.responsibilities == ["Design APIs", "Lead code reviews"]
        assert mock_record.required_skills[0]["skill_id"] == "skill_python"
        assert mock_record.structured_profile is not None

    def test_upsert_rolls_back_on_db_error(self):
        """Any DB error during commit must trigger a rollback and re-raise."""
        repo = JobRequirementRepository()
        profile = _make_profile()

        mock_record = MagicMock()
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_record
        mock_session.commit.side_effect = Exception("DB connection lost")

        with patch("src.db.repositories.job_requirement_repository.SessionLocal", return_value=mock_session):
            with pytest.raises(Exception, match="DB connection lost"):
                repo.upsert(job_id="valid-uuid", profile=profile)

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    def test_upsert_without_job_id_not_called(self):
        """
        The router is responsible for NOT calling upsert when job_id is None.
        This test verifies the upsert method itself does NOT crash on an empty string.
        """
        repo = JobRequirementRepository()
        profile = _make_profile()

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch("src.db.repositories.job_requirement_repository.SessionLocal", return_value=mock_session):
            result = repo.upsert(job_id="", profile=profile)

        assert result is False
