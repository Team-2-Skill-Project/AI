"""Jooble-to-SkillMatch normalization with no inferred job requirements."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from src.schemas.job import JobPosting

from .models import RawJoobleJob


def clean_snippet(value: str | None) -> str | None:
    """Remove markup/entities and normalize whitespace without rewriting content."""
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _as_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def normalize_jooble_job(raw: RawJoobleJob, *, ingested_at: datetime | None = None) -> JobPosting:
    """Map source fields only; enrichment fields intentionally remain unknown."""
    cleaned_description = clean_snippet(raw.snippet)
    ingested = ingested_at or datetime.now(timezone.utc)
    return JobPosting(
        job_id=f"jooble:{raw.external_id}",
        title=raw.title,
        role=raw.title,
        company=raw.company,
        description=cleaned_description,
        location=raw.location,
        work_mode=None,
        employment_type=raw.employment_type,
        canonical_role=None,
        role_family=None,
        experience_level=None,
        min_years_experience=None,
        posted_at=None,
        expires_at=None,
        source_url=raw.source_url,
        salary=raw.salary,
        source="jooble",
        source_external_id=raw.external_id,
        source_updated_at=_as_utc_naive(raw.source_updated_at),
        ingested_at=_as_utc_naive(ingested),
        description_is_partial=True,
        required_skills=[],
    )
