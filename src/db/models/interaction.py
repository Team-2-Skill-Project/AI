from __future__ import annotations
"""
SQLAlchemy ORM model for candidate-job interaction events.

Tracks behavioral events (view, click, save, apply, dismiss) linking
real candidates and jobs with timestamps and optional interaction metadata.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, String, Index
from sqlalchemy.dialects.sqlite import JSON

from src.db.base import Base


class CandidateInteractionModel(Base):
    """Database representation of an interaction event between a candidate and a job."""

    __tablename__ = "candidate_interactions"
    __table_args__ = (
        Index("ix_cand_job_interaction", "candidate_id", "job_id"),
        Index("ix_cand_event_type", "candidate_id", "event_type"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(100), nullable=False, index=True)
    job_id = Column(String(100), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)  # view, click, save, apply, dismiss
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
