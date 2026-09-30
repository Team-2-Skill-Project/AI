"""Global pytest database isolation.

This module is imported by pytest before test modules import ``src``.  Set a
per-run temporary SQLite URL at that point so production singletons construct
their engines against the test database, never ``skillmatch.db``.
"""

from __future__ import annotations

import os

import pytest


TEST_DATABASE_URL = "sqlite://"

# Deliberately overwrite a developer-provided DATABASE_URL for the pytest
# process only.  Runtime commands do not import this module.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"


def _close_long_lived_test_sessions() -> None:
    """Release singleton sessions before rebuilding the temporary schema."""
    try:
        from src.services.recommendation_service import recommendation_service

        close = getattr(recommendation_service.job_repo, "close", None)
        if callable(close):
            close()
    except Exception:
        # A test may exercise only a subsystem which has not initialized the
        # recommendation singleton.  The schema reset below remains safe.
        pass


def _reset_test_database() -> None:
    from src.db.base import Base, engine

    # Register every production ORM mapping once before creating the clean
    # temporary schema.  Seed data is deliberately not shared between tests;
    # registry-aware paths bootstrap their own explicit inputs as production
    # code does on first use.
    import src.db.models.candidate  # noqa: F401
    import src.db.models.interaction  # noqa: F401
    import src.db.models.interview  # noqa: F401
    import src.db.models.job_requirement  # noqa: F401
    import src.db.models.match  # noqa: F401
    import src.db.models.roadmap  # noqa: F401
    import src.db.models.review_queue  # noqa: F401
    import src.db.models.skill_registry  # noqa: F401
    import src.db.models.skill_resource  # noqa: F401

    _close_long_lived_test_sessions()
    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _temporary_database_lifecycle():
    """Dispose and remove the per-run database after all tests complete."""
    yield
    from src.db.base import engine

    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_database_for_each_test():
    """Make test order irrelevant for database-backed application paths."""
    _reset_test_database()
    yield
    _reset_test_database()
