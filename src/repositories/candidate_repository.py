"""Candidate profile storage used by candidate-dependent application flows.

The MVP keeps profiles in memory, matching the existing mock job and behavior
repositories.  A database-backed implementation can later satisfy the same
small contract without changing recommendation orchestration.
"""

from abc import ABC, abstractmethod
from typing import Dict, Iterable, Optional

from src.models.candidate import (
    Candidate,
    CandidatePreferences,
    CandidateProfile,
    CandidateProfileDetails,
    CandidateSkill,
    EvidenceItem,
    SkillLevel,
    UserProfile,
)


class CandidateRepository(ABC):
    """Accesses complete candidate profiles by their stable identifier."""

    @abstractmethod
    def get_candidate(self, candidate_id: str) -> Optional[Candidate]:
        """Returns the stored profile or ``None`` when the candidate is unknown."""

    @abstractmethod
    def save_candidate(self, candidate: Candidate) -> Candidate:
        """Stores the latest complete profile for the candidate."""


def _seed_candidates() -> Iterable[Candidate]:
    """Provides the local demonstration profile used by the recommendation API."""
    yield Candidate(
        candidate_id="cand_001",
        user=UserProfile(name="Demo Backend Candidate"),
        candidate_profile=CandidateProfile(
            location="Riyadh, Saudi Arabia",
        ),
        target_roles=["Backend Engineer"],
        preferences=CandidatePreferences(
            work_mode=["remote"],
            locations=["Riyadh", "Cairo"],
            employment_type=["full_time"],
        ),
        candidate_skills=[
            CandidateSkill(
                skill_id="skill_python",
                name="Python",
                proficiency="advanced",
                evidence=[EvidenceItem(text="Built backend services with Python.")],
            ),
            CandidateSkill(
                skill_id="skill_fastapi",
                name="FastAPI",
                proficiency="advanced",
                evidence=[EvidenceItem(text="Implemented REST APIs with FastAPI.")],
            ),
            CandidateSkill(
                skill_id="skill_postgresql",
                name="PostgreSQL",
                proficiency="advanced",
                evidence=[EvidenceItem(text="Designed PostgreSQL data models.")],
            ),
        ],
    )


class MockCandidateRepository(CandidateRepository):
    """In-memory candidate profile store for local API use and tests."""

    def __init__(self, candidates: Optional[Iterable[Candidate]] = None):
        initial_candidates = candidates if candidates is not None else _seed_candidates()
        self._candidates: Dict[str, Candidate] = {
            candidate.candidate_id: candidate for candidate in initial_candidates
        }

    def get_candidate(self, candidate_id: str) -> Optional[Candidate]:
        return self._candidates.get(candidate_id)

    def save_candidate(self, candidate: Candidate) -> Candidate:
        self._candidates[candidate.candidate_id] = candidate
        return candidate


class _LazyCandidateRepository(CandidateRepository):
    """Runtime proxy that delegates to DatabaseCandidateRepository without circular import."""

    def __init__(self) -> None:
        self._delegate: Optional[CandidateRepository] = None

    def _get_delegate(self) -> CandidateRepository:
        if self._delegate is None:
            from src.db.repositories.candidate_repository import DatabaseCandidateRepository
            self._delegate = DatabaseCandidateRepository()
        return self._delegate

    def get_candidate(self, candidate_id: str) -> Optional[Candidate]:
        return self._get_delegate().get_candidate(candidate_id)

    def save_candidate(self, candidate: Candidate) -> Candidate:
        return self._get_delegate().save_candidate(candidate)


# Production runtime candidate repository backed by database persistence
candidate_repository: CandidateRepository = _LazyCandidateRepository()


def __getattr__(name: str):
    if name == "DatabaseCandidateRepository":
        from src.db.repositories.candidate_repository import DatabaseCandidateRepository
        return DatabaseCandidateRepository
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "CandidateRepository",
    "DatabaseCandidateRepository",
    "MockCandidateRepository",
    "candidate_repository",
    "_seed_candidates",
]
