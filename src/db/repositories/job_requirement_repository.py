from __future__ import annotations
"""
Repository for persisting JobRequirementProfile results to the jobs table.

Pattern mirrors src/db/repositories/match_repository.py.

The upsert() method is intentionally non-raising:
  - Returns True  if the job record was found and updated successfully.
  - Returns False if the job_id does not exist in the DB (no-op, no exception).
"""

import logging

from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models.job_requirement import JobRequirementModel
from src.job_extractor.models import JobRequirementProfile

logger = logging.getLogger(__name__)


def _get_db() -> Session:
    """Return a new DB session."""
    return SessionLocal()


class JobRequirementRepository:
    """
    Provides upsert access to the AI-contract columns on the jobs table.

    Unlike BaseRepository, this class manages its own session lifetime
    so it can be instantiated without a pre-existing session (useful in the
    router where no DB session dependency is injected by default).
    """

    def upsert(self, job_id: str, profile: JobRequirementProfile) -> bool:
        """
        Update the AI-contract columns on an existing jobs row.

        Args:
            job_id:  Primary key of the job to update.
            profile: Fully resolved JobRequirementProfile.

        Returns:
            True  — row was found and updated.
            False — row not found (no exception raised).
        """
        db: Session = _get_db()
        try:
            record = db.query(JobRequirementModel).filter(JobRequirementModel.id == job_id).first()
            if record is None:
                logger.warning(
                    "JobRequirementRepository.upsert: job_id='%s' not found in DB — skipping.",
                    job_id,
                )
                return False

            record.canonical_role = profile.canonical_role
            record.min_years_experience = profile.min_years_experience
            record.max_years_experience = profile.max_years_experience
            record.responsibilities = profile.responsibilities
            # Keep the canonical catalog field in sync with the structured profile.
            record.required_skills = [skill.model_dump(mode="json") for skill in profile.required_skills]
            record.structured_profile = profile.model_dump(mode="json")

            db.commit()
            logger.info(
                "JobRequirementRepository.upsert: updated job_id='%s' successfully.", job_id
            )
            return True
        except Exception as e:
            db.rollback()
            logger.error(
                "JobRequirementRepository.upsert: DB error for job_id='%s': %s",
                job_id,
                e,
                exc_info=True,
            )
            raise
        finally:
            db.close()
