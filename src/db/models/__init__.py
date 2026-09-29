from __future__ import annotations
"""SQLAlchemy models."""

from src.db.models.candidate import CandidateModel
from src.db.models.interaction import CandidateInteractionModel

__all__ = ["CandidateModel", "CandidateInteractionModel"]
