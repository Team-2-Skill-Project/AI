"""Database-backed persistence repository for candidate-job interaction behavior."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.base import SessionLocal
from src.db.models.candidate import CandidateModel
from src.db.models.interaction import CandidateInteractionModel
from src.db.models.job_requirement import JobRequirementModel
from src.repositories.behavior_repository import BehaviorRepository
from src.schemas.recommendation import CandidateBehaviorHistory

logger = logging.getLogger(__name__)

SUPPORTED_INTERACTION_TYPES = {"view", "click", "save", "unsave", "apply", "dismiss", "undismiss"}

SYNONYM_MAP = {
    "viewed": "view",
    "clicked": "click",
    "saved": "save",
    "bookmark": "save",
    "bookmarked": "save",
    "unsaved": "unsave",
    "unbookmark": "unsave",
    "applied": "apply",
    "dismissed": "dismiss",
    "hide": "dismiss",
    "hidden": "dismiss",
    "undismissed": "undismiss",
    "unhide": "undismiss",
}


class DatabaseBehaviorRepository(BehaviorRepository):
    """Database-backed implementation of candidate interaction tracking."""

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
        """Expose current database session for compatibility."""
        return self._external_db or SessionLocal()

    @staticmethod
    def normalize_interaction_type(interaction_type: str) -> str:
        """Normalizes interaction type string to canonical token or raises ValueError."""
        if not interaction_type or not str(interaction_type).strip():
            raise ValueError("Interaction type cannot be empty.")
        clean = str(interaction_type).lower().strip()
        canonical = SYNONYM_MAP.get(clean, clean)
        if canonical not in SUPPORTED_INTERACTION_TYPES:
            raise ValueError(
                f"Unsupported interaction type '{interaction_type}'. "
                f"Supported types are: {', '.join(sorted(SUPPORTED_INTERACTION_TYPES))}"
            )
        return canonical

    def get_candidate_behavior(self, candidate_id: str) -> CandidateBehaviorHistory:
        """
        Retrieves interaction history for a candidate reconstructed from persisted events.
        
        Guarantees deterministic, non-contradictory state:
          - Applied jobs remain in applied_job_ids.
          - Save and dismiss have consistent state transitions (save cancels dismiss, dismiss cancels save).
          - Views and clicks populate viewed_job_ids without duplicates.
          - Returns an empty baseline for new candidates with no fabrication.
        """
        if not candidate_id or not str(candidate_id).strip():
            return CandidateBehaviorHistory()

        cid = str(candidate_id).strip()
        session = self._get_session()
        try:
            records = (
                session.query(CandidateInteractionModel)
                .filter(CandidateInteractionModel.candidate_id == cid)
                .order_by(CandidateInteractionModel.created_at.asc(), CandidateInteractionModel.id.asc())
                .all()
            )

            if not records:
                return CandidateBehaviorHistory()

            saved_set: set[str] = set()
            applied_set: set[str] = set()
            dismissed_set: set[str] = set()
            viewed_set: set[str] = set()

            # Preserve arrival order for stable list representation
            saved_order: list[str] = []
            applied_order: list[str] = []
            dismissed_order: list[str] = []
            viewed_order: list[str] = []

            for record in records:
                etype = record.event_type
                jid = record.job_id

                if etype in ("view", "click"):
                    if jid not in viewed_set:
                        viewed_set.add(jid)
                        viewed_order.append(jid)
                elif etype == "apply":
                    if jid not in applied_set:
                        applied_set.add(jid)
                        applied_order.append(jid)
                    # Once applied, dismissed is cleared; applied jobs are active
                    if jid in dismissed_set:
                        dismissed_set.remove(jid)
                        if jid in dismissed_order:
                            dismissed_order.remove(jid)
                elif etype == "save":
                    if jid not in saved_set:
                        saved_set.add(jid)
                        saved_order.append(jid)
                    # Saving cancels previous dismissal
                    if jid in dismissed_set:
                        dismissed_set.remove(jid)
                        if jid in dismissed_order:
                            dismissed_order.remove(jid)
                elif etype == "unsave":
                    if jid in saved_set:
                        saved_set.remove(jid)
                        if jid in saved_order:
                            saved_order.remove(jid)
                elif etype == "dismiss":
                    # Applied jobs cannot be dismissed
                    if jid not in applied_set:
                        if jid not in dismissed_set:
                            dismissed_set.add(jid)
                            dismissed_order.append(jid)
                        # Dismissing removes active save
                        if jid in saved_set:
                            saved_set.remove(jid)
                            if jid in saved_order:
                                saved_order.remove(jid)
                elif etype == "undismiss":
                    if jid in dismissed_set:
                        dismissed_set.remove(jid)
                        if jid in dismissed_order:
                            dismissed_order.remove(jid)

            return CandidateBehaviorHistory(
                saved_job_ids=saved_order,
                applied_job_ids=applied_order,
                dismissed_job_ids=dismissed_order,
                viewed_job_ids=viewed_order,
            )
        finally:
            self._close_session_if_owned(session)

    def record_interaction(
        self,
        candidate_id: str,
        job_id: str,
        interaction_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CandidateInteractionModel:
        """
        Records an interaction event with idempotency and state consistency.
        
        - View/click events are always appended with exact timestamp.
        - Save/apply/dismiss are checked against current state to prevent duplicate
          redundant entries while preserving transition semantics.
        """
        if not candidate_id or not str(candidate_id).strip():
            raise ValueError("Candidate ID must not be empty.")
        if not job_id or not str(job_id).strip():
            raise ValueError("Job ID must not be empty.")

        cid = str(candidate_id).strip()
        jid = str(job_id).strip()
        canonical_type = self.normalize_interaction_type(interaction_type)

        session = self._get_session()
        try:
            if session.get(CandidateModel, cid) is None:
                raise LookupError(f"Candidate '{cid}' was not found.")
            if session.get(JobRequirementModel, jid) is None:
                raise LookupError(f"Job '{jid}' was not found.")

            # Check current state for state-changing events (save, apply, dismiss)
            if canonical_type in ("save", "apply", "dismiss", "unsave", "undismiss"):
                current_behavior = self.get_candidate_behavior(cid)

                if canonical_type == "save" and jid in current_behavior.saved_job_ids:
                    # Already saved and not dismissed -> idempotent return of latest record
                    latest = (
                        session.query(CandidateInteractionModel)
                        .filter(
                            CandidateInteractionModel.candidate_id == cid,
                            CandidateInteractionModel.job_id == jid,
                            CandidateInteractionModel.event_type == "save",
                        )
                        .order_by(CandidateInteractionModel.created_at.desc())
                        .first()
                    )
                    if latest:
                        return latest

                if canonical_type == "apply" and jid in current_behavior.applied_job_ids:
                    # Already applied -> idempotent
                    latest = (
                        session.query(CandidateInteractionModel)
                        .filter(
                            CandidateInteractionModel.candidate_id == cid,
                            CandidateInteractionModel.job_id == jid,
                            CandidateInteractionModel.event_type == "apply",
                        )
                        .order_by(CandidateInteractionModel.created_at.desc())
                        .first()
                    )
                    if latest:
                        return latest

                if canonical_type == "dismiss":
                    if jid in current_behavior.applied_job_ids:
                        # Cannot dismiss already applied job
                        logger.info("Ignoring dismiss for already-applied job %s by candidate %s", jid, cid)
                        latest = (
                            session.query(CandidateInteractionModel)
                            .filter(
                                CandidateInteractionModel.candidate_id == cid,
                                CandidateInteractionModel.job_id == jid,
                                CandidateInteractionModel.event_type == "apply",
                            )
                            .order_by(CandidateInteractionModel.created_at.desc())
                            .first()
                        )
                        if latest:
                            return latest
                    if jid in current_behavior.dismissed_job_ids:
                        # Already dismissed -> idempotent
                        latest = (
                            session.query(CandidateInteractionModel)
                            .filter(
                                CandidateInteractionModel.candidate_id == cid,
                                CandidateInteractionModel.job_id == jid,
                                CandidateInteractionModel.event_type == "dismiss",
                            )
                            .order_by(CandidateInteractionModel.created_at.desc())
                            .first()
                        )
                        if latest:
                            return latest

            # Insert new interaction event record
            record = CandidateInteractionModel(
                candidate_id=cid,
                job_id=jid,
                event_type=canonical_type,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                metadata_json=metadata,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record
        except Exception:
            session.rollback()
            raise
        finally:
            self._close_session_if_owned(session)

    def get_interaction_counts(self, candidate_id: str, job_id: str) -> Dict[str, int]:
        """Returns the total number of events per type for a candidate-job pair."""
        cid = str(candidate_id).strip()
        jid = str(job_id).strip()
        session = self._get_session()
        try:
            records = (
                session.query(CandidateInteractionModel)
                .filter(
                    CandidateInteractionModel.candidate_id == cid,
                    CandidateInteractionModel.job_id == jid,
                )
                .all()
            )
            counts: Dict[str, int] = {}
            for r in records:
                counts[r.event_type] = counts.get(r.event_type, 0) + 1
            return counts
        finally:
            self._close_session_if_owned(session)

    def clear_candidate_interactions(self, candidate_id: str) -> int:
        """Removes all interaction events for a given candidate."""
        cid = str(candidate_id).strip()
        session = self._get_session()
        try:
            count = (
                session.query(CandidateInteractionModel)
                .filter(CandidateInteractionModel.candidate_id == cid)
                .delete(synchronize_session=False)
            )
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise
        finally:
            self._close_session_if_owned(session)
