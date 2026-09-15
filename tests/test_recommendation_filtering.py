"""Unit tests for recommendation candidate filtering and 5-tuple deduplication."""

import pytest
from datetime import datetime, timezone, timedelta
from src.schemas.job import JobPosting, SkillRequirement
from src.schemas.recommendation import CandidateBehaviorHistory
from src.services.recommendation_service import RecommendationService


@pytest.fixture
def service():
    return RecommendationService()


def test_candidate_hard_filters(service):
    """Verify applied, dismissed, and structurally invalid jobs are removed."""
    now = datetime.now(timezone.utc)

    jobs = [
        JobPosting(job_id="job_valid", title="Backend Engineer", is_active=True),
        JobPosting(job_id="job_applied", title="Backend Engineer", is_active=True),
        JobPosting(job_id="job_dismissed", title="Backend Engineer", is_active=True),
        JobPosting(job_id="job_no_title", title="", is_active=True),
        JobPosting(job_id="", title="Valid Title", is_active=True),
    ]

    behavior = CandidateBehaviorHistory(
        applied_job_ids=["job_applied"],
        dismissed_job_ids=["job_dismissed"],
        saved_job_ids=["job_valid"],
    )

    filtered = service.filter_candidate_jobs(jobs, behavior)
    filtered_ids = [j.job_id for j in filtered]

    assert "job_valid" in filtered_ids
    assert "job_applied" not in filtered_ids
    assert "job_dismissed" not in filtered_ids
    assert "job_no_title" not in filtered_ids
    assert "" not in filtered_ids
    assert len(filtered) == 1


def test_deduplication_exact_id_and_url(service):
    """Verify exact job_id and source_url duplicates collapse."""
    jobs = [
        JobPosting(job_id="job_001", title="Backend Engineer", company="TechCorp", source_url="https://site.com/1"),
        JobPosting(job_id="job_001", title="Backend Engineer", company="TechCorp", source_url="https://site.com/1"),
        JobPosting(job_id="job_002", title="Backend Engineer", company="TechCorp", source_url="https://site.com/1"),  # duplicate URL
        JobPosting(job_id="job_003", title="Data Engineer", company="TechCorp", source_url="https://site.com/3"),
    ]

    deduped = service.deduplicate_jobs(jobs)
    deduped_ids = [j.job_id for j in deduped]

    assert len(deduped) == 2
    assert "job_001" in deduped_ids
    assert "job_003" in deduped_ids


def test_deduplication_5_tuple_keeps_freshest(service):
    """Verify identical 5-tuple postings keep the newest record."""
    now = datetime.now(timezone.utc)
    dt_old = now - timedelta(days=10)
    dt_new = now - timedelta(days=1)

    jobs = [
        JobPosting(
            job_id="job_old",
            title="Backend Engineer",
            company="TechCorp",
            work_mode="remote",
            location="Riyadh",
            employment_type="full_time",
            posted_at=dt_old,
        ),
        JobPosting(
            job_id="job_new",
            title="Backend Engineer",
            company="TechCorp",
            work_mode="remote",
            location="Riyadh",
            employment_type="full_time",
            posted_at=dt_new,
        ),
    ]

    deduped = service.deduplicate_jobs(jobs)
    assert len(deduped) == 1
    assert deduped[0].job_id == "job_new"


def test_deduplication_preserves_legitimate_variants(service):
    """Verify distinct work modes, locations, and employment types are preserved."""
    jobs = [
        # Remote variant
        JobPosting(
            job_id="job_remote",
            title="Backend Engineer",
            company="TechCorp",
            work_mode="remote",
            location="Cairo",
            employment_type="full_time",
        ),
        # Onsite variant
        JobPosting(
            job_id="job_onsite",
            title="Backend Engineer",
            company="TechCorp",
            work_mode="onsite",
            location="Cairo",
            employment_type="full_time",
        ),
        # Different location
        JobPosting(
            job_id="job_riyadh",
            title="Backend Engineer",
            company="TechCorp",
            work_mode="remote",
            location="Riyadh",
            employment_type="full_time",
        ),
        # Different employment type
        JobPosting(
            job_id="job_intern",
            title="Backend Engineer",
            company="TechCorp",
            work_mode="remote",
            location="Cairo",
            employment_type="internship",
        ),
    ]

    deduped = service.deduplicate_jobs(jobs)
    assert len(deduped) == 4
    deduped_ids = [j.job_id for j in deduped]
    assert "job_remote" in deduped_ids
    assert "job_onsite" in deduped_ids
    assert "job_riyadh" in deduped_ids
    assert "job_intern" in deduped_ids
