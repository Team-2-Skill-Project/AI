from __future__ import annotations
import logging
from typing import Generator
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
# pyrefly: ignore [missing-import]
from src.core.config import settings

logger = logging.getLogger(__name__)

# Configure connect arguments (allow multithreaded access for SQLite)
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency providing a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    """Creates all database tables defined in the metadata."""
    try:
        # Import models so they register with Base.metadata before create_all
        import src.db.models.match
        import src.db.models.review_queue
        import src.db.models.interview
        import src.db.models.job_requirement  # noqa: F401 — registers AI-contract columns
        import src.db.models.roadmap
        import src.db.models.skill_resource

        Base.metadata.create_all(bind=engine)
        _ensure_job_columns()
        logger.info("Database tables verified and initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database tables: {e}", exc_info=True)


def _ensure_job_columns() -> None:
    """Add canonical ingestion columns to legacy jobs tables without data loss."""
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("jobs")}
    columns = {
        "title": "VARCHAR(300)",
        "company": "VARCHAR(300)",
        "role": "VARCHAR(300)",
        "role_family": "VARCHAR(150)",
        "description": "TEXT",
        "department": "VARCHAR(150)",
        "location": "VARCHAR(300)",
        "work_mode": "VARCHAR(50)",
        "employment_type": "VARCHAR(100)",
        "experience_level": "VARCHAR(100)",
        "posted_at": "DATETIME",
        "expires_at": "DATETIME",
        "is_active": "INTEGER",
        "source_url": "VARCHAR(1000)",
        "required_skills": "JSON",
        "salary": "VARCHAR(300)",
        "source": "VARCHAR(100)",
        "source_external_id": "VARCHAR(300)",
        "source_updated_at": "DATETIME",
        "ingested_at": "DATETIME",
        "description_is_partial": "INTEGER",
    }

    missing = [(name, sql_type) for name, sql_type in columns.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name, sql_type in missing:
            connection.execute(text(f'ALTER TABLE jobs ADD COLUMN "{name}" {sql_type}'))
