"""Persistence adapter for canonical source-ingested jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models.job_requirement import JobRequirementModel
from src.job_extractor.models import JobRequirementProfile
from src.repositories.job_repository import JobRepository
from src.schemas.job import JobPosting, SkillRequirement


@dataclass(frozen=True)
class UpsertOutcome:
    created: bool
    job_id: str


class DatabaseJobRepository(JobRepository):
    """Upsert canonical jobs using source identity before URL identity."""

    def __init__(self, db: Session | None = None) -> None:
        self._owns_session = db is None
        self.db = db or SessionLocal()

    def close(self) -> None:
        if self._owns_session:
            self.db.close()

    @staticmethod
    def _skill_requirements(raw_skills: object) -> list[SkillRequirement]:
        if not isinstance(raw_skills, list):
            return []
        requirements: list[SkillRequirement] = []
        for item in raw_skills:
            if isinstance(item, str):
                requirements.append(SkillRequirement(skill_name=item))
                continue
            if not isinstance(item, dict):
                continue
            name = item.get("skill_name") or item.get("canonical_name") or item.get("name")
            if not name:
                continue
            requirements.append(
                SkillRequirement(
                    skill_name=str(name),
                    proficiency=str(item.get("proficiency") or item.get("required_level") or "Intermediate"),
                    is_critical=bool(item.get("is_critical")) or item.get("importance") == "critical",
                    category=item.get("category"),
                    min_years_experience=item.get("min_years_experience"),
                    description=item.get("description"),
                )
            )
        return requirements

    @classmethod
    def _to_job_posting(cls, record: JobRequirementModel) -> JobPosting:
        profile = record.structured_profile if isinstance(record.structured_profile, dict) else {}
        skills = record.required_skills or profile.get("required_skills", [])
        return JobPosting(
            job_id=record.id,
            title=record.title or "",
            company=record.company,
            role=record.role,
            canonical_role=record.canonical_role or profile.get("canonical_role"),
            role_family=record.role_family or profile.get("role_family"),
            description=record.description,
            department=record.department,
            location=record.location,
            work_mode=record.work_mode,
            employment_type=record.employment_type,
            experience_level=record.experience_level or profile.get("seniority"),
            min_years_experience=record.min_years_experience or profile.get("min_years_experience"),
            posted_at=record.posted_at,
            expires_at=record.expires_at,
            is_active=bool(record.is_active),
            source_url=record.source_url,
            required_skills=cls._skill_requirements(skills),
            salary=record.salary,
            source=record.source,
            source_external_id=record.source_external_id,
            source_updated_at=record.source_updated_at,
            ingested_at=record.ingested_at,
            description_is_partial=bool(record.description_is_partial),
        )

    def get_active_jobs(
        self,
        work_mode: str | None = None,
        location: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[JobPosting]:
        """Return usable active jobs; do not reject Jooble rows only for null posted_at."""
        now = datetime.now(timezone.utc)
        records = self.db.query(JobRequirementModel).filter(JobRequirementModel.is_active == 1).all()
        jobs: list[JobPosting] = []
        for record in records:
            if not (record.title or "").strip() or not (record.company or "").strip() or not (record.source_url or "").strip():
                continue
            if record.expires_at:
                expiry = record.expires_at
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry < now:
                    continue
            job = self._to_job_posting(record)
            if work_mode and (job.work_mode or "").lower() != work_mode.lower():
                continue
            if location and location.lower() not in (job.location or "").lower():
                continue
            jobs.append(job)

        if offset > 0:
            jobs = jobs[offset:]
        if limit is not None and limit > 0:
            jobs = jobs[:limit]
        return jobs

    def get_job_by_id(self, job_id: str) -> JobPosting | None:
        record = self.db.get(JobRequirementModel, job_id)
        return self._to_job_posting(record) if record is not None else None

    def _find_existing(self, job: JobPosting) -> JobRequirementModel | None:
        conditions = []
        if job.source and job.source_external_id:
            conditions.append(
                and_(
                    JobRequirementModel.source == job.source,
                    JobRequirementModel.source_external_id == job.source_external_id,
                )
            )
        if job.source_url:
            if job.source:
                conditions.append(
                    and_(
                        JobRequirementModel.source == job.source,
                        JobRequirementModel.source_url == job.source_url,
                    )
                )
            else:
                conditions.append(JobRequirementModel.source_url == job.source_url)
        if not conditions:
            return self.db.get(JobRequirementModel, job.job_id)
        return self.db.query(JobRequirementModel).filter(or_(*conditions)).first()

    @staticmethod
    def _datetime(value: datetime | str | None) -> datetime | None:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
            except ValueError:
                return None
        return None

    def upsert(self, job: JobPosting, *, profile: JobRequirementProfile | None = None) -> UpsertOutcome:
        record = self._find_existing(job)
        created = record is None
        if record is None:
            record = JobRequirementModel(id=job.job_id)
            self.db.add(record)

        record.title = job.title
        record.company = job.company
        record.role = job.role
        record.role_family = job.role_family
        record.description = job.description
        record.location = job.location
        record.work_mode = job.work_mode
        record.employment_type = job.employment_type
        record.experience_level = job.experience_level
        record.posted_at = self._datetime(job.posted_at)
        record.expires_at = self._datetime(job.expires_at)
        record.is_active = 1 if job.is_active else 0
        record.source_url = job.source_url
        record.salary = job.salary
        record.source = job.source
        record.source_external_id = job.source_external_id
        record.source_updated_at = self._datetime(job.source_updated_at)
        record.ingested_at = self._datetime(job.ingested_at)
        record.description_is_partial = 1 if job.description_is_partial else 0
        record.required_skills = [skill.model_dump(mode="json") for skill in job.required_skills]

        if profile is not None:
            record.canonical_role = profile.canonical_role
            record.role_family = profile.role_family
            record.experience_level = profile.seniority
            record.min_years_experience = profile.min_years_experience
            record.max_years_experience = profile.max_years_experience
            record.responsibilities = profile.responsibilities
            record.structured_profile = profile.model_dump(mode="json")
            record.required_skills = [skill.model_dump(mode="json") for skill in profile.required_skills]

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return UpsertOutcome(created=created, job_id=record.id)
