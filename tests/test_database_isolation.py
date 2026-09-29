"""Regression guard for pytest database isolation."""

from src.core.config import BASE_DIR, settings
from src.db.base import engine


def test_pytest_engine_never_targets_the_runtime_database():
    runtime_database = (BASE_DIR / "skillmatch.db").resolve()

    assert settings.DATABASE_URL == "sqlite://"
    assert engine.url.database is None
    assert str(engine.url) != f"sqlite:///{runtime_database.as_posix()}"
