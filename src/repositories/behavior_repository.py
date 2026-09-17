"""Abstract interface and mock implementation for candidate interaction behavior.

Decouples recommendation scoring from candidate interaction persistence.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from src.schemas.recommendation import CandidateBehaviorHistory


class BehaviorRepository(ABC):
    """Abstract base class for accessing candidate behavior history."""

    @abstractmethod
    def get_candidate_behavior(self, candidate_id: str) -> CandidateBehaviorHistory:
        """Retrieves interaction history (saved, applied, dismissed job IDs) for a candidate."""
        pass

    @abstractmethod
    def record_interaction(
        self,
        candidate_id: str,
        job_id: str,
        interaction_type: str,
    ) -> None:
        """Records a user interaction (save, apply, dismiss, view)."""
        pass


class MockBehaviorRepository(BehaviorRepository):
    """In-memory mock store for candidate interactions during testing."""

    def __init__(self, initial_data: Optional[Dict[str, CandidateBehaviorHistory]] = None):
        self._store: Dict[str, CandidateBehaviorHistory] = initial_data or {
            # Default mock behavior for testing
            "cand_001": CandidateBehaviorHistory(
                saved_job_ids=["job_030"],
                applied_job_ids=["job_028"],
                dismissed_job_ids=["job_029"],
                viewed_job_ids=["job_001", "job_002"]
            ),
            "cand_python_senior": CandidateBehaviorHistory(
                saved_job_ids=["job_001", "job_030"],
                applied_job_ids=["job_028"],
                dismissed_job_ids=["job_029"],
                viewed_job_ids=[]
            )
        }

    def get_candidate_behavior(self, candidate_id: str) -> CandidateBehaviorHistory:
        """Returns candidate history or an empty baseline object if new candidate."""
        if candidate_id not in self._store:
            self._store[candidate_id] = CandidateBehaviorHistory()
        return self._store[candidate_id]

    def record_interaction(
        self,
        candidate_id: str,
        job_id: str,
        interaction_type: str,
    ) -> None:
        """Appends interaction to candidate's history."""
        history = self.get_candidate_behavior(candidate_id)
        norm_type = interaction_type.lower().strip()

        if norm_type in ("save", "saved") and job_id not in history.saved_job_ids:
            history.saved_job_ids.append(job_id)
        elif norm_type in ("apply", "applied") and job_id not in history.applied_job_ids:
            history.applied_job_ids.append(job_id)
        elif norm_type in ("dismiss", "dismissed", "hide") and job_id not in history.dismissed_job_ids:
            history.dismissed_job_ids.append(job_id)
        elif norm_type in ("view", "viewed") and job_id not in history.viewed_job_ids:
            history.viewed_job_ids.append(job_id)
