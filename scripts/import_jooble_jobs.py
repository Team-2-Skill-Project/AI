"""Controlled development import of one bounded Jooble Egypt result page."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import settings
from src.db.base import init_db
from src.db.repositories.job_repository import DatabaseJobRepository
from src.integrations.jooble import JoobleClient, JoobleIngestionService
from src.job_extractor.pipeline import JobExtractionPipeline


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Import a bounded Jooble Egypt page into SkillMatch")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    if not settings.JOOBLE_API_KEY:
        parser.error("JOOBLE_API_KEY is not configured")
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")

    init_db()
    repository = DatabaseJobRepository()
    try:
        service = JoobleIngestionService(
            client=JoobleClient(),
            repository=repository,
            extraction_pipeline=JobExtractionPipeline(),
        )
        summary = service.ingest(keywords=args.keywords, location=args.location, limit=args.limit)
    finally:
        repository.close()

    print(
        " ".join(
            [
                f"fetched={summary.fetched}",
                f"created={summary.created}",
                f"updated={summary.updated}",
                f"duplicates_skipped={summary.duplicates_skipped}",
                f"extraction_successes={summary.extraction_successes}",
                f"extraction_failures={summary.extraction_failures}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
