"""Redis cache coverage for personalized recommendation feeds.

These tests use a small Redis protocol double.  Production code continues to
use the shared RedisManager and intentionally has no in-process cache fallback.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.repositories.candidate_repository import DatabaseCandidateRepository
from src.models.candidate import Candidate, CandidatePreferences, CandidateProfileDetails, CandidateSkill, SkillLevel
from src.repositories.behavior_repository import MockBehaviorRepository
from src.schemas.job import JobPosting, SkillRequirement
from src.schemas.recommendation import CandidateBehaviorHistory
from src.services.matching_service import MatchingService
from src.services.recommendation_cache import RecommendationFeedCache
from src.services.recommendation_service import RecommendationService


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int]] = []
        self.get_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.fail_get = False
        self.fail_set = False

    def get(self, key: str):
        self.get_calls.append(key)
        if self.fail_get:
            raise RuntimeError("temporary redis read failure")
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int):
        if self.fail_set:
            raise RuntimeError("temporary redis write failure")
        self.set_calls.append((key, value, ex))
        self.data[key] = value
        return True

    def delete(self, key: str):
        self.delete_calls.append(key)
        self.data.pop(key, None)
        return 1


class InMemoryJobRepository:
    def __init__(self, jobs: list[JobPosting]) -> None:
        self.jobs = jobs
        self.calls = 0

    def get_active_jobs(self, work_mode=None, location=None, limit=None, offset=0):
        self.calls += 1
        jobs = list(self.jobs)
        if work_mode:
            jobs = [job for job in jobs if (job.work_mode or "").lower() == work_mode.lower()]
        if location:
            jobs = [job for job in jobs if location.lower() in (job.location or "").lower()]
        return jobs[offset:] if limit is None else jobs[offset : offset + limit]


class CountingMatchingService(MatchingService):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def evaluate_match(self, *args, **kwargs):
        self.calls += 1
        return super().evaluate_match(*args, **kwargs)


@pytest.fixture
def redis_cache(monkeypatch):
    from src.services import recommendation_cache as cache_module

    fake = FakeRedis()
    monkeypatch.setattr(cache_module, "is_redis_available", lambda: True)
    monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
    return fake, RecommendationFeedCache(ttl_seconds=600)


@pytest.fixture
def candidate():
    return Candidate(
        candidate_id="candidate-cache-a",
        profile=CandidateProfileDetails(name="Cache Candidate", target_roles=["Backend Engineer"]),
        skills=[CandidateSkill(skill_id="skill_python", name="Python", level=SkillLevel.ADVANCED)],
        preferences=CandidatePreferences(work_mode=["remote"], locations=["Cairo"]),
    )


@pytest.fixture
def job():
    return JobPosting(
        job_id="job-cache-1",
        title="Python Backend Engineer",
        company="Cache Co",
        location="Cairo",
        work_mode="remote",
        source_url="https://example.test/jobs/cache-1",
        source="test",
        source_external_id="cache-1",
        posted_at=datetime.now(timezone.utc),
        required_skills=[SkillRequirement(skill_id="skill_python", skill_name="Python", proficiency="advanced")],
    )


def _service(jobs, behavior, cache):
    matcher = CountingMatchingService()
    return (
        RecommendationService(
            job_repository=InMemoryJobRepository(jobs),
            behavior_repository=behavior,
            matching_svc=matcher,
            feed_cache=cache,
        ),
        matcher,
    )


def test_identical_feed_is_cached_with_configured_ttl(redis_cache, candidate, job):
    fake, cache = redis_cache
    service, matcher = _service([job], MockBehaviorRepository({}), cache)

    first = asyncio.run(service.get_recommendation_feed(candidate, limit=10))
    second = asyncio.run(service.get_recommendation_feed(candidate, limit=10))

    assert matcher.calls == 1
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert len(fake.set_calls) == 1
    assert fake.set_calls[0][2] == 600


def test_candidate_and_filter_state_never_share_cache_entries(redis_cache, candidate, job):
    fake, cache = redis_cache
    service, matcher = _service([job], MockBehaviorRepository({}), cache)
    candidate_b = candidate.model_copy(update={"candidate_id": "candidate-cache-b"})

    asyncio.run(service.get_recommendation_feed(candidate, limit=10, location="Cairo"))
    asyncio.run(service.get_recommendation_feed(candidate_b, limit=10, location="Cairo"))
    asyncio.run(service.get_recommendation_feed(candidate, limit=5, location="Cairo"))
    asyncio.run(service.get_recommendation_feed(candidate, limit=10, location="Other"))
    asyncio.run(service.get_recommendation_feed(candidate, limit=10, location="Cairo", min_score=1))

    assert matcher.calls == 4  # Different location has no jobs, so no matching work.
    assert len(fake.data) == 5
    assert len(set(fake.data)) == 5


def test_pagination_parameters_are_part_of_the_cache_key(redis_cache, candidate, job):
    _, cache = redis_cache
    behavior = CandidateBehaviorHistory()
    first = cache.build_key(candidate=candidate, behavior=behavior, jobs=[job], page=1, limit=10, work_mode=None, location=None, min_score=0)
    second = cache.build_key(candidate=candidate, behavior=behavior, jobs=[job], page=2, limit=10, work_mode=None, location=None, min_score=0)

    assert first != second


@pytest.mark.parametrize("event_type", ["save", "apply", "dismiss"])
def test_interactions_change_key_and_recompute_feed(redis_cache, candidate, job, event_type):
    _, cache = redis_cache
    behavior = MockBehaviorRepository({})
    service, matcher = _service([job], behavior, cache)

    before = asyncio.run(service.get_recommendation_feed(candidate, limit=10))
    behavior.record_interaction(candidate.candidate_id, job.job_id, event_type)
    after = asyncio.run(service.get_recommendation_feed(candidate, limit=10))

    assert matcher.calls == (2 if event_type == "save" else 1)
    if event_type == "save":
        assert before.recommendations[0].score_breakdown.behavior_boost == 50.0
        assert after.recommendations[0].score_breakdown.behavior_boost == 100.0
    else:
        assert after.recommendations == []


def test_views_and_clicks_do_not_invalidate_when_they_do_not_affect_scoring(redis_cache, candidate, job):
    _, cache = redis_cache
    behavior = MockBehaviorRepository({})
    service, matcher = _service([job], behavior, cache)

    asyncio.run(service.get_recommendation_feed(candidate, limit=10))
    behavior.record_interaction(candidate.candidate_id, job.job_id, "view")
    asyncio.run(service.get_recommendation_feed(candidate, limit=10))
    behavior.record_interaction(candidate.candidate_id, job.job_id, "click")
    asyncio.run(service.get_recommendation_feed(candidate, limit=10))

    assert matcher.calls == 1


def test_profile_and_preference_changes_from_persistence_change_the_key(redis_cache, candidate, job):
    _, cache = redis_cache
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repository = DatabaseCandidateRepository(session)
    repository.save_candidate(candidate)
    stored = repository.get_candidate(candidate.candidate_id)
    behavior = CandidateBehaviorHistory()
    key_before = cache.build_key(candidate=stored, behavior=behavior, jobs=[job], page=1, limit=10, work_mode=None, location=None, min_score=0)

    updated = stored.model_copy(
        update={
            "candidate_skills": stored.candidate_skills + [CandidateSkill(skill_id="skill_fastapi", name="FastAPI", level=SkillLevel.ADVANCED)],
            "preferences": CandidatePreferences(work_mode=["hybrid"], locations=["Cairo"]),
        }
    )
    repository.save_candidate(updated)
    refreshed = repository.get_candidate(candidate.candidate_id)
    key_after = cache.build_key(candidate=refreshed, behavior=behavior, jobs=[job], page=1, limit=10, work_mode=None, location=None, min_score=0)

    assert key_before != key_after


def test_catalog_change_recomputes_but_a_noop_does_not(redis_cache, candidate, job):
    _, cache = redis_cache
    service, matcher = _service([job], MockBehaviorRepository({}), cache)

    initial = asyncio.run(service.get_recommendation_feed(candidate, limit=10))
    new_job = job.model_copy(update={"job_id": "job-cache-2", "title": "Python API Engineer", "source_url": "https://example.test/jobs/cache-2", "source_external_id": "cache-2"})
    service.job_repo.jobs = [job, new_job]
    after_insert = asyncio.run(service.get_recommendation_feed(candidate, limit=10))
    service.job_repo.jobs = [job, new_job.model_copy(update={"title": "Senior Python Backend Engineer"})]
    asyncio.run(service.get_recommendation_feed(candidate, limit=10))
    asyncio.run(service.get_recommendation_feed(candidate, limit=10))

    assert [item.job_id for item in initial.recommendations] == [job.job_id]
    assert {item.job_id for item in after_insert.recommendations} == {job.job_id, new_job.job_id}
    assert matcher.calls == 5


def test_redis_unavailable_and_read_write_failures_fall_back_to_live_computation(monkeypatch, candidate, job):
    from src.services import recommendation_cache as cache_module

    cache = RecommendationFeedCache(ttl_seconds=600)
    behavior = MockBehaviorRepository({})
    matcher = CountingMatchingService()
    service = RecommendationService(
        job_repository=InMemoryJobRepository([job]),
        behavior_repository=behavior,
        matching_svc=matcher,
        feed_cache=cache,
    )

    monkeypatch.setattr(cache_module, "is_redis_available", lambda: False)
    assert asyncio.run(service.get_recommendation_feed(candidate, limit=10)).recommendations
    assert asyncio.run(service.get_recommendation_feed(candidate, limit=10)).recommendations
    assert matcher.calls == 2

    failing = FakeRedis()
    failing.fail_get = True
    monkeypatch.setattr(cache_module, "is_redis_available", lambda: True)
    monkeypatch.setattr(cache_module, "get_redis_client", lambda: failing)
    assert asyncio.run(service.get_recommendation_feed(candidate, limit=11)).recommendations
    failing.fail_get = False
    failing.fail_set = True
    assert asyncio.run(service.get_recommendation_feed(candidate, limit=12)).recommendations


def test_malformed_cached_response_is_discarded_and_empty_feed_can_be_cached(redis_cache, candidate, job):
    fake, cache = redis_cache
    behavior = MockBehaviorRepository({})
    service, matcher = _service([job], behavior, cache)
    key = cache.build_key(
        candidate=candidate,
        behavior=behavior.get_candidate_behavior(candidate.candidate_id),
        jobs=[job],
        page=1,
        limit=10,
        work_mode=None,
        location=None,
        min_score=0,
    )
    fake.data[key] = "not-json"
    assert asyncio.run(service.get_recommendation_feed(candidate, limit=10)).recommendations
    assert matcher.calls == 1
    assert key in fake.delete_calls

    empty_service, empty_matcher = _service([], MockBehaviorRepository({}), cache)
    first = asyncio.run(empty_service.get_recommendation_feed(candidate, limit=10))
    second = asyncio.run(empty_service.get_recommendation_feed(candidate, limit=10))
    assert first.recommendations == second.recommendations == []
    assert empty_matcher.calls == 0


def test_cached_scoring_matches_uncached_scoring(redis_cache, candidate, job, monkeypatch):
    from src.services import recommendation_cache as cache_module

    _, cache = redis_cache
    live_service, _ = _service([job], MockBehaviorRepository({}), cache)
    cached = asyncio.run(live_service.get_recommendation_feed(candidate, limit=10))

    monkeypatch.setattr(cache_module, "is_redis_available", lambda: False)
    uncached_service, _ = _service([job], MockBehaviorRepository({}), RecommendationFeedCache(ttl_seconds=600))
    uncached = asyncio.run(uncached_service.get_recommendation_feed(candidate, limit=10))

    assert [(item.job_id, item.score, item.score_breakdown) for item in cached.recommendations] == [
        (item.job_id, item.score, item.score_breakdown) for item in uncached.recommendations
    ]
