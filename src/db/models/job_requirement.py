from __future__ import annotations
"""
SQLAlchemy ORM model for persisting job requirement profiles.

Maps to the *existing* ``jobs`` table using ``extend_existing=True`` to avoid
redefining it; the canonical job and AI-contract columns are declared here.

Columns declared here mirror the BACKEND_SCHEMA.md contract:
  - canonical_role        VARCHAR(150)
  - min_years_experience  INT
  - max_years_experience  INT
  - responsibilities      JSON
  - structured_profile    JSON   (full JobRequirementProfile blob)
"""

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON  # falls back gracefully on PostgreSQL

from src.db.base import Base


class JobRequirementModel(Base):
    """
    Extends the backend ``jobs`` table with AI-extracted requirement fields.

    ``extend_existing=True`` ensures this model co-exists with any other
    SQLAlchemy model already mapped to the same table (e.g. the backend ORM).
    """

    __tablename__ = "jobs"
    __table_args__ = {"extend_existing": True}

    # Primary key — mirrors the backend jobs.id column (UUID stored as string)
    id = Column(String, primary_key=True)

    # Canonical job fields used by source ingestion and downstream consumers.
    title = Column(String(300), nullable=False, default="")
    company = Column(String(300), nullable=True)
    role = Column(String(300), nullable=True)
    role_family = Column(String(150), nullable=True)
    description = Column(Text, nullable=True)
    department = Column(String(150), nullable=True)
    location = Column(String(300), nullable=True)
    work_mode = Column(String(50), nullable=True)
    employment_type = Column(String(100), nullable=True)
    experience_level = Column(String(100), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Integer, nullable=False, default=1)
    source_url = Column(String(1000), nullable=True)
    required_skills = Column(JSON, nullable=True)
    salary = Column(String(300), nullable=True)
    source = Column(String(100), nullable=True, index=True)
    source_external_id = Column(String(300), nullable=True, index=True)
    source_updated_at = Column(DateTime, nullable=True)
    ingested_at = Column(DateTime, nullable=True)
    description_is_partial = Column(Integer, nullable=False, default=0)

    # ── AI-contract columns (added via BACKEND_SCHEMA.md migration) ───
    canonical_role = Column(String(150), nullable=True)
    min_years_experience = Column(Integer, nullable=True)
    max_years_experience = Column(Integer, nullable=True)
    responsibilities = Column(JSON, nullable=True)

    # Full structured profile blob for downstream consumers (search, matching)
    structured_profile = Column(JSON, nullable=True)
