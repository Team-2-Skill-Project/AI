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
    CandidateProfileDetails,
    CandidateSkill,
    EvidenceItem,
    SkillLevel,
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
        profile=CandidateProfileDetails(
            name="Demo Backend Candidate",
            target_roles=["Backend Engineer"],
            preferences=CandidatePreferences(
                work_mode=["remote"],
                locations=["Riyadh", "Cairo"],
                employment_type=["full_time"],
            ),
        ),
        skills=[
            CandidateSkill(
                skill_id="skill_python",
                name="Python",
                level=SkillLevel.ADVANCED,
                evidence=[EvidenceItem(text="Built backend services with Python.")],
            ),
            CandidateSkill(
                skill_id="skill_fastapi",
                name="FastAPI",
                level=SkillLevel.ADVANCED,
                evidence=[EvidenceItem(text="Implemented REST APIs with FastAPI.")],
            ),
            CandidateSkill(
                skill_id="skill_postgresql",
                name="PostgreSQL",
                level=SkillLevel.ADVANCED,
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


candidate_repository = MockCandidateRepository()
