from __future__ import annotations
import logging
from typing import Generator
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool
# pyrefly: ignore [missing-import]
from src.core.config import settings

logger = logging.getLogger(__name__)

# Configure connect arguments (allow multithreaded access for SQLite)
connect_args = {}
engine_options = {"echo": False, "pool_pre_ping": True}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Pytest sets this URL before importing the application.  StaticPool keeps the
# same in-memory SQLite database visible to TestClient worker threads while
# remaining entirely separate from the runtime database.
if settings.ENVIRONMENT == "test" and settings.DATABASE_URL == "sqlite://":
    engine_options["poolclass"] = StaticPool

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    **engine_options,
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
        import src.db.models.skill_registry  # noqa: F401 - registers registry tables
        import src.db.models.candidate  # noqa: F401 - registers candidates table
        import src.db.models.interaction  # noqa: F401 - registers candidate_interactions table

        Base.metadata.create_all(bind=engine)
        _ensure_job_columns()
        _bootstrap_skill_registry()
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


def _bootstrap_skill_registry() -> None:
    """Load the small trusted seed into the persistent registry idempotently."""
    from src.db.repositories.skill_registry_repository import SkillRegistryRepository
    from src.taxonomy.skill_registry_resolver import SkillRegistryResolver
    from src.taxonomy.taxonomy_manager import TaxonomyManager

    session = SessionLocal()
    try:
        taxonomy = TaxonomyManager()
        SkillRegistryRepository(session).bootstrap_seed(
            taxonomy.get_all_skills(),
            SkillRegistryResolver.normalized_name,
        )
    finally:
        session.close()
