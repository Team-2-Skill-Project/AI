from __future__ import annotations
"""
SQLAlchemy ORM model for persisting candidate profiles.

Stores structured candidate data extracted from CVs or provided via API,
preserving canonical skill identities, evidence, proficiencies, target roles,
and candidate preferences.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.sqlite import JSON

from src.db.base import Base


class CandidateModel(Base):
    """Database representation of a candidate profile."""

    __tablename__ = "candidates"
    __table_args__ = {"extend_existing": True}

    # Primary key — candidate identifier (e.g. cand_001, cand_12345678, or UUID)
    id = Column(String(100), primary_key=True)

    # Core user & contact attributes
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(100), nullable=True)
    location = Column(String(255), nullable=True)
    headline = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    linkedin_url = Column(String(500), nullable=True)
    github_url = Column(String(500), nullable=True)
    portfolio_url = Column(String(500), nullable=True)

    # Structured collections & AI domains
    target_roles = Column(JSON, nullable=True)
    preferences = Column(JSON, nullable=True)
    skills = Column(JSON, nullable=True)
    experiences = Column(JSON, nullable=True)
    educations = Column(JSON, nullable=True)
    projects = Column(JSON, nullable=True)
    certificates = Column(JSON, nullable=True)
    languages = Column(JSON, nullable=True)

    # Complete high-fidelity serialized Candidate model
    raw_profile = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
