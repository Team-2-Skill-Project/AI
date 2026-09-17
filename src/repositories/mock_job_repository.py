from __future__ import annotations
"""Mock Job Repository implementation backed by static seed fixtures.

Used during local testing and MVP execution while the live Job Feed ingestion
system is under development. Can be swapped with DatabaseJobRepository or
APIJobRepository in production without altering the recommendation engine.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Union

from src.repositories.job_repository import JobRepository
from src.schemas.job import JobPosting, SkillRequirement

logger = logging.getLogger(__name__)


def _parse_iso_datetime(dt_val: Any) -> Optional[datetime]:
    """Helper to safely parse ISO timestamp strings into datetime objects."""
    if isinstance(dt_val, datetime):
        return dt_val
    if isinstance(dt_val, str) and dt_val.strip():
        try:
            # Handle Z suffix for UTC
            clean_str = dt_val.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_str)
        except Exception:
            return None
    return None


class MockJobRepository(JobRepository):
    """
    In-memory mock job repository that reads from jobs_seed.json.
    Completely candidate-agnostic, supporting standard catalog queries.
    """

    def __init__(self, seed_path: Optional[Union[str, Path]] = None):
        if seed_path is None:
            base_dir = Path(__file__).resolve().parent.parent
            self.seed_path = base_dir / "fixtures" / "jobs_seed.json"
        else:
            self.seed_path = Path(seed_path)

        self._jobs: Dict[str, JobPosting] = {}
        self._load_seed_data()

    def _load_seed_data(self) -> None:
        """Loads and parses raw JSON jobs into validated JobPosting models."""
        if not self.seed_path.exists():
            logger.warning(f"Mock job seed file not found at '{self.seed_path}'. Initializing empty catalog.")
            return

        try:
            with open(self.seed_path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)

            for item in raw_list:
                job_id = item.get("job_id")
                if not job_id:
                    continue

                req_skills = []
                for s in item.get("required_skills", []):
                    req_skills.append(SkillRequirement.from_any(s))

                posted_dt = _parse_iso_datetime(item.get("posted_at"))
                expires_dt = _parse_iso_datetime(item.get("expires_at"))

                job = JobPosting(
                    job_id=job_id,
                    title=item.get("title", "Untitled Job"),
                    company=item.get("company"),
                    role=item.get("role"),
                    canonical_role=item.get("canonical_role"),
                    role_family=item.get("role_family"),
                    description=item.get("description"),
                    department=item.get("department"),
                    location=item.get("location"),
                    work_mode=item.get("work_mode", "remote"),
                    employment_type=item.get("employment_type", "full_time"),
                    experience_level=item.get("experience_level"),
                    min_years_experience=item.get("min_years_experience"),
                    posted_at=posted_dt,
                    expires_at=expires_dt,
                    is_active=bool(item.get("is_active", True)),
                    source_url=item.get("source_url"),
                    required_skills=req_skills,
                )
                self._jobs[job.job_id] = job

            logger.info(f"Loaded {len(self._jobs)} jobs into MockJobRepository from '{self.seed_path}'")
        except Exception as e:
            logger.error(f"Failed to load mock jobs seed: {e}", exc_info=True)

    def get_active_jobs(
        self,
        work_mode: Optional[str] = None,
        location: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[JobPosting]:
        """Returns all non-expired, active jobs matching catalog-level filters."""
        now = datetime.now(timezone.utc)
        results: List[JobPosting] = []

        for job in self._jobs.values():
            # 1. Check active flag
            if not job.is_active:
                continue

            # 2. Check expiration timestamp
            if job.expires_at:
                exp_dt = job.expires_at if isinstance(job.expires_at, datetime) else _parse_iso_datetime(job.expires_at)
                if exp_dt:
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if exp_dt < now:
                        continue

            # 3. Optional catalog filters
            if work_mode and job.work_mode and work_mode.lower() != job.work_mode.lower():
                continue

            if location and job.location and location.lower() not in job.location.lower():
                continue

            results.append(job)

        # Apply offset and limit
        if offset > 0:
            results = results[offset:]
        if limit is not None and limit > 0:
            results = results[:limit]

        return results

    def get_job_by_id(self, job_id: str) -> Optional[JobPosting]:
        """Returns single job by ID or None."""
        return self._jobs.get(job_id)
