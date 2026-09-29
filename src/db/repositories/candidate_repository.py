"""Persistence repository for structured candidate profiles."""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models.candidate import CandidateModel
from src.models.candidate import (
    Candidate,
    CandidatePreferences,
    CandidateProfile,
    CandidateSkill,
    CertificateItem,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    ProjectItem,
    UserProfile,
)
from src.repositories.candidate_repository import CandidateRepository

logger = logging.getLogger(__name__)


class DatabaseCandidateRepository(CandidateRepository):
    """Database-backed implementation of CandidateRepository."""

    def __init__(self, db: Session | None = None) -> None:
        self._external_db = db

    def _get_session(self) -> Session:
        if self._external_db is not None:
            return self._external_db
        return SessionLocal()

    def _close_session_if_owned(self, session: Session) -> None:
        if self._external_db is None:
            session.close()

    @property
    def db(self) -> Session:
        """Expose current database session for base compatibility."""
        return self._external_db or SessionLocal()

    @classmethod
    def _to_candidate(cls, record: CandidateModel) -> Candidate:
        """Constructs a high-fidelity Candidate domain model from a database record."""
        # 1. Prefer full-fidelity raw_profile JSON blob if present
        if record.raw_profile:
            raw = record.raw_profile
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = None
            if isinstance(raw, dict):
                try:
                    return Candidate.model_validate(raw)
                except Exception as exc:
                    logger.warning("Failed to validate raw_profile for candidate %s: %s", record.id, exc)

        # 2. Reconstruct from explicit database columns
        user = UserProfile(
            name=record.name,
            email=record.email,
        )
        candidate_profile = CandidateProfile(
            phone=record.phone,
            location=record.location,
            headline=record.headline,
            bio=record.bio,
            linkedin_url=record.linkedin_url,
            github_url=record.github_url,
            portfolio_url=record.portfolio_url,
        )

        preferences_data = record.preferences if isinstance(record.preferences, dict) else {}
        preferences = CandidatePreferences.model_validate(preferences_data)

        target_roles = list(record.target_roles or [])

        candidate_skills: list[CandidateSkill] = []
        if isinstance(record.skills, list):
            for s in record.skills:
                if isinstance(s, dict):
                    try:
                        candidate_skills.append(CandidateSkill.model_validate(s))
                    except Exception:
                        pass

        experiences: list[ExperienceItem] = []
        if isinstance(record.experiences, list):
            for exp in record.experiences:
                if isinstance(exp, dict):
                    try:
                        experiences.append(ExperienceItem.model_validate(exp))
                    except Exception:
                        pass

        educations: list[EducationItem] = []
        if isinstance(record.educations, list):
            for edu in record.educations:
                if isinstance(edu, dict):
                    try:
                        educations.append(EducationItem.model_validate(edu))
                    except Exception:
                        pass

        projects: list[ProjectItem] = []
        if isinstance(record.projects, list):
            for proj in record.projects:
                if isinstance(proj, dict):
                    try:
                        projects.append(ProjectItem.model_validate(proj))
                    except Exception:
                        pass

        certificates: list[CertificateItem] = []
        if isinstance(record.certificates, list):
            for cert in record.certificates:
                if isinstance(cert, dict):
                    try:
                        certificates.append(CertificateItem.model_validate(cert))
                    except Exception:
                        pass

        languages: list[LanguageItem] = []
        if isinstance(record.languages, list):
            for lang in record.languages:
                if isinstance(lang, dict):
                    try:
                        languages.append(LanguageItem.model_validate(lang))
                    except Exception:
                        pass

        return Candidate(
            candidate_id=record.id,
            user=user,
            candidate_profile=candidate_profile,
            target_roles=target_roles,
            preferences=preferences,
            candidate_skills=candidate_skills,
            experiences=experiences,
            educations=educations,
            projects=projects,
            certificates=certificates,
            languages=languages,
        )

    def get_candidate(self, candidate_id: str) -> Optional[Candidate]:
        """Retrieves a stored candidate profile by ID or returns None."""
        if not candidate_id or not str(candidate_id).strip():
            return None

        session = self._get_session()
        try:
            record = session.query(CandidateModel).filter(CandidateModel.id == str(candidate_id).strip()).first()
            if record is None:
                return None
            return self._to_candidate(record)
        finally:
            self._close_session_if_owned(session)

    def save_candidate(self, candidate: Candidate) -> Candidate:
        """Stores or updates the structured candidate profile."""
        if not candidate or not candidate.candidate_id:
            raise ValueError("Candidate must have a valid candidate_id to be persisted.")

        session = self._get_session()
        try:
            cid = candidate.candidate_id.strip()
            record = session.query(CandidateModel).filter(CandidateModel.id == cid).first()
            if record is None:
                record = CandidateModel(id=cid)
                session.add(record)

            # Extract user & profile details
            record.name = candidate.user.name if candidate.user else None
            record.email = candidate.user.email if candidate.user else None

            prof = candidate.candidate_profile
            record.phone = prof.phone if prof else None
            record.location = prof.location if prof else None
            record.headline = prof.headline if prof else None
            record.bio = prof.bio if prof else None
            record.linkedin_url = str(prof.linkedin_url) if prof and prof.linkedin_url else None
            record.github_url = str(prof.github_url) if prof and prof.github_url else None
            record.portfolio_url = str(prof.portfolio_url) if prof and prof.portfolio_url else None

            # Collections and AI domains
            record.target_roles = list(candidate.target_roles or [])
            record.preferences = candidate.preferences.model_dump(mode="json") if candidate.preferences else {}
            record.skills = [s.model_dump(mode="json") for s in (candidate.candidate_skills or [])]
            record.experiences = [e.model_dump(mode="json") for e in (candidate.experiences or [])]
            record.educations = [e.model_dump(mode="json") for e in (candidate.educations or [])]
            record.projects = [p.model_dump(mode="json") for p in (candidate.projects or [])]
            record.certificates = [c.model_dump(mode="json") for c in (candidate.certificates or [])]
            record.languages = [l.model_dump(mode="json") for l in (candidate.languages or [])]

            # High fidelity serialized blob
            record.raw_profile = candidate.model_dump(mode="json")

            session.commit()
            return candidate
        except Exception:
            session.rollback()
            raise
        finally:
            self._close_session_if_owned(session)

    def delete_candidate(self, candidate_id: str) -> bool:
        """Removes a candidate profile from the repository."""
        if not candidate_id:
            return False

        session = self._get_session()
        try:
            record = session.query(CandidateModel).filter(CandidateModel.id == candidate_id).first()
            if record:
                session.delete(record)
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise
        finally:
            self._close_session_if_owned(session)
