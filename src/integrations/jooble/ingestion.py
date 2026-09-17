"""Controlled Jooble ingestion orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from src.core.config import settings
from src.db.repositories.job_repository import DatabaseJobRepository
from src.job_extractor.pipeline import JobExtractionPipeline

from .client import JoobleClient
from .normalizer import normalize_jooble_job

logger = logging.getLogger(__name__)


@dataclass
class IngestionSummary:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    duplicates_skipped: int = 0
    extraction_successes: int = 0
    extraction_failures: int = 0


class JoobleIngestionService:
    """Fetch, normalize, deduplicate, enrich, and persist a bounded page."""

    def __init__(
        self,
        client: JoobleClient,
        repository: DatabaseJobRepository,
        extraction_pipeline: JobExtractionPipeline | None = None,
    ) -> None:
        self.client = client
        self.repository = repository
        self.extraction_pipeline = extraction_pipeline

    def ingest(self, *, keywords: str, location: str, limit: int = 5) -> IngestionSummary:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        raw_jobs = self.client.search(
            keywords=keywords,
            location=location,
            page=1,
            result_on_page=limit,
        )
        summary = IngestionSummary(fetched=len(raw_jobs))
        seen_ids: set[str] = set()
        seen_urls: set[str] = set()

        for raw in raw_jobs:
            normalized_url = (raw.source_url or "").strip().lower()
            if raw.external_id in seen_ids or (normalized_url and normalized_url in seen_urls):
                summary.duplicates_skipped += 1
                continue
            seen_ids.add(raw.external_id)
            if normalized_url:
                seen_urls.add(normalized_url)

            job = normalize_jooble_job(raw)
            profile: Any = None
            if self.extraction_pipeline is not None and job.description:
                try:
                    profile = self.extraction_pipeline.extract(job.description)
                    summary.extraction_successes += 1
                except Exception as exc:
                    summary.extraction_failures += 1
                    logger.warning(
                        "Job extraction failed: job_id=%s source_external_id=%s "
                        "stage=job_extraction error_type=%s message=%s",
                        job.job_id,
                        job.source_external_id,
                        type(exc).__name__,
                        _safe_error_message(exc),
                    )

            outcome = self.repository.upsert(job, profile=profile)
            if outcome.created:
                summary.created += 1
            else:
                summary.updated += 1
        return summary


def _safe_error_message(exc: Exception, limit: int = 300) -> str:
    """Return a bounded error message with configured secrets redacted."""
    message = " ".join(str(exc).split())
    secrets = [settings.JOOBLE_API_KEY, settings.get_llm_settings().api_key]
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:limit] + ("..." if len(message) > limit else "")
