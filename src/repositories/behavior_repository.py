"""Abstract interface, in-memory mock, and lazy runtime proxy for candidate interaction behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from src.schemas.recommendation import CandidateBehaviorHistory


class BehaviorRepository(ABC):
    """Abstract base class for accessing candidate behavior history."""

    @abstractmethod
    def get_candidate_behavior(self, candidate_id: Optional[str]) -> CandidateBehaviorHistory:
        """Retrieves interaction history (saved, applied, dismissed job IDs) for a candidate."""
        pass

    @abstractmethod
    def record_interaction(
        self,
        candidate_id: str,
        job_id: str,
        interaction_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Records a user interaction (save, apply, dismiss, view, click)."""
        pass


class MockBehaviorRepository(BehaviorRepository):
    """In-memory mock store for candidate interactions during testing."""

    def __init__(self, initial_data: Optional[Dict[str, CandidateBehaviorHistory]] = None):
        self._store: Dict[str, CandidateBehaviorHistory] = initial_data if initial_data is not None else {
            "cand_001": CandidateBehaviorHistory(
                saved_job_ids=["job_030"],
                applied_job_ids=["job_028"],
                dismissed_job_ids=["job_029"],
                viewed_job_ids=["job_001", "job_002"],
            ),
            "cand_python_senior": CandidateBehaviorHistory(
                saved_job_ids=["job_001", "job_030"],
                applied_job_ids=["job_028"],
                dismissed_job_ids=["job_029"],
                viewed_job_ids=[],
            ),
        }

    def get_candidate_behavior(self, candidate_id: Optional[str]) -> CandidateBehaviorHistory:
        """Returns candidate history or an empty baseline object if new candidate."""
        if not candidate_id or not candidate_id.strip():
            return CandidateBehaviorHistory()
        cid = candidate_id.strip()
        if cid not in self._store:
            self._store[cid] = CandidateBehaviorHistory()
        return self._store[cid]

    def record_interaction(
        self,
        candidate_id: str,
        job_id: str,
        interaction_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Appends interaction to candidate's history in memory."""
        history = self.get_candidate_behavior(candidate_id)
        norm_type = interaction_type.lower().strip()

        if norm_type in ("save", "saved", "bookmark", "bookmarked") and job_id not in history.saved_job_ids:
            history.saved_job_ids.append(job_id)
        elif norm_type in ("apply", "applied") and job_id not in history.applied_job_ids:
            history.applied_job_ids.append(job_id)
        elif norm_type in ("dismiss", "dismissed", "hide", "hidden") and job_id not in history.dismissed_job_ids:
            history.dismissed_job_ids.append(job_id)
        elif norm_type in ("view", "viewed", "click", "clicked") and job_id not in history.viewed_job_ids:
            history.viewed_job_ids.append(job_id)
        elif norm_type in ("unsave", "unsaved", "unbookmark") and job_id in history.saved_job_ids:
            history.saved_job_ids.remove(job_id)
        elif norm_type in ("undismiss", "undismissed", "unhide") and job_id in history.dismissed_job_ids:
            history.dismissed_job_ids.remove(job_id)
        return metadata


class _LazyBehaviorRepository(BehaviorRepository):
    """Runtime proxy resolving DatabaseBehaviorRepository lazily to prevent circular imports."""

    def __init__(self) -> None:
        self._delegate: Optional[BehaviorRepository] = None

    def _get_delegate(self) -> BehaviorRepository:
        if self._delegate is None:
            from src.db.repositories.behavior_repository import DatabaseBehaviorRepository
            self._delegate = DatabaseBehaviorRepository()
        return self._delegate

    def get_candidate_behavior(self, candidate_id: Optional[str]) -> CandidateBehaviorHistory:
        return self._get_delegate().get_candidate_behavior(candidate_id)

    def record_interaction(
        self,
        candidate_id: str,
        job_id: str,
        interaction_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return self._get_delegate().record_interaction(candidate_id, job_id, interaction_type, metadata=metadata)

    def __getattr__(self, name: str):
        """Expose database-only diagnostic/maintenance methods through the proxy."""
        return getattr(self._get_delegate(), name)


# Production runtime candidate behavior repository backed by database persistence
behavior_repository: BehaviorRepository = _LazyBehaviorRepository()


def __getattr__(name: str):
    if name == "DatabaseBehaviorRepository":
        from src.db.repositories.behavior_repository import DatabaseBehaviorRepository
        return DatabaseBehaviorRepository
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "BehaviorRepository",
    "DatabaseBehaviorRepository",
    "MockBehaviorRepository",
    "behavior_repository",
]
