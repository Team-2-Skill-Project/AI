"""Job repository interfaces and implementations facade."""

from __future__ import annotations

from src.db.repositories.job_repository import (
    DatabaseJobRepository,
    JobRepository,
    UpsertOutcome,
)

__all__ = [
    "JobRepository",
    "DatabaseJobRepository",
    "UpsertOutcome",
]
