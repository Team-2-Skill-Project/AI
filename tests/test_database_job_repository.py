from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.models.job_requirement import JobRequirementModel
from src.db.repositories.job_repository import DatabaseJobRepository
from src.models.candidate import Candidate, CandidateProfileDetails, CandidateSkill, SkillLevel
from src.repositories.behavior_repository import MockBehaviorRepository
from src.services.matching_service import MatchingService
from src.services.recommendation_service import RecommendationService


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _record(job_id="jooble:db-1", **overrides):
    values = {
        "id": job_id,
        "title": "Python Developer",
        "company": "DB Company",
        "description": "Python API development",
        "location": "Cairo",
        "work_mode": None,
        "employment_type": None,
        "source_url": "https://eg.jooble.org/jdp/db-1",
        "required_skills": [{"canonical_name": "Python", "required_level": "advanced", "importance": "critical"}],
        "source": "jooble",
        "source_external_id": "db-1",
        "source_updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "is_active": 1,
        "description_is_partial": 1,
    }
    values.update(overrides)
    return JobRequirementModel(**values)


def test_database_repository_returns_only_usable_active_jobs_and_maps_skills():
    db = _session()
    db.add_all(
        [
            _record(),
            _record("inactive", is_active=0, source_external_id="inactive"),
            _record("expired", expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1), source_external_id="expired"),
            _record("no-url", source_url=None, source_external_id="no-url"),
        ]
    )
    db.commit()

    repo = DatabaseJobRepository(db)
    jobs = repo.get_active_jobs()

    assert [job.job_id for job in jobs] == ["jooble:db-1"]
    assert jobs[0].required_skills[0].skill_name == "Python"
    assert jobs[0].required_skills[0].is_critical is True
    assert jobs[0].posted_at is None
    assert jobs[0].source_updated_at is not None
    assert repo.get_job_by_id("jooble:db-1").source == "jooble"


def test_recommendation_service_defaults_to_database_repository():
    service = RecommendationService()
    assert isinstance(service.job_repo, DatabaseJobRepository)
    service.job_repo.close()


@pytest.mark.asyncio
async def test_database_job_enters_existing_recommendation_pipeline():
    db = _session()
    db.add(_record())
    db.commit()
    candidate = Candidate(
        candidate_id="db-candidate",
        profile=CandidateProfileDetails(name="DB Candidate", target_roles=["Python Developer"]),
        skills=[CandidateSkill(skill_id="skill_python", name="Python", level=SkillLevel.ADVANCED)],
    )

    service = RecommendationService(
        job_repository=DatabaseJobRepository(db),
        behavior_repository=MockBehaviorRepository({}),
        matching_svc=MatchingService(),
    )
    feed = await service.get_recommendation_feed(candidate, limit=10)

    assert [item.job_id for item in feed.recommendations] == ["jooble:db-1"]
    assert feed.recommendations[0].score >= 0
