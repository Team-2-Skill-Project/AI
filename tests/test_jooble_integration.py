from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from src.db.base import Base
from src.db.models.job_requirement import JobRequirementModel
from src.db.repositories.job_repository import DatabaseJobRepository
from src.integrations.jooble.client import JoobleClient
from src.integrations.jooble.ingestion import JoobleIngestionService
from src.integrations.jooble.models import RawJoobleJob
from src.integrations.jooble.normalizer import clean_snippet, normalize_jooble_job
from src.job_extractor.models import JobRequirementProfile, NormalizedSkill


def _raw(external_id: str = "123", **overrides) -> RawJoobleJob:
    payload = {
        "id": external_id,
        "title": "Python Developer",
        "company": "Example Co",
        "location": "Cairo, Egypt",
        "snippet": "<b>Python</b>&nbsp;developer needed",
        "salary": "",
        "type": "",
        "source": "example.com",
        "link": f"https://eg.jooble.org/jdp/{external_id}",
        "updated": "2026-08-26T00:00:00.0000000",
    }
    payload.update(overrides)
    return RawJoobleJob.from_payload(payload)


def test_client_parses_mocked_response_without_network():
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"totalCount": 1, "jobs": [_raw().raw_payload]}).encode()

    client = JoobleClient(api_key="test-key", opener=lambda request, timeout: FakeResponse())
    jobs = client.search(keywords="Python Developer", location="Egypt", result_on_page=1)

    assert len(jobs) == 1
    assert jobs[0].external_id == "123"
    assert jobs[0].raw_payload["source"] == "example.com"


def test_clean_snippet_removes_tags_entities_and_extra_whitespace():
    assert clean_snippet("<b>Python</b>&nbsp; developer\nneeded") == "Python developer needed"


def test_normalization_maps_source_fields_and_does_not_invent_requirements():
    job = normalize_jooble_job(_raw(), ingested_at=datetime(2026, 9, 15))

    assert job.job_id == "jooble:123"
    assert job.title == "Python Developer"
    assert job.role == "Python Developer"
    assert job.description == "Python developer needed"
    assert job.source == "jooble"
    assert job.source_external_id == "123"
    assert job.source_url.endswith("/123")
    assert job.description_is_partial is True
    assert job.work_mode is None
    assert job.canonical_role is None
    assert job.required_skills == []


def test_missing_salary_and_type_are_preserved_as_none():
    job = normalize_jooble_job(_raw(salary="", type=""))
    assert job.salary is None
    assert job.employment_type is None


def test_repository_persists_source_metadata_and_updates_existing_record():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    repo = DatabaseJobRepository(session)

    first = normalize_jooble_job(_raw(), ingested_at=datetime(2026, 9, 15))
    second = normalize_jooble_job(
        _raw(title="Senior Python Developer", snippet="<b>Updated</b> listing"),
        ingested_at=datetime(2026, 9, 16),
    )

    assert repo.upsert(first).created is True
    assert repo.upsert(second).created is False
    stored = session.execute(select(JobRequirementModel)).scalar_one()

    assert stored.title == "Senior Python Developer"
    assert stored.source == "jooble"
    assert stored.source_external_id == "123"
    assert stored.description_is_partial == 1


def test_ingestion_skips_duplicate_payloads_before_persistence():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    raw = _raw()

    class FakeClient:
        def search(self, **kwargs):
            return [raw, raw.model_copy()]

    service = JoobleIngestionService(FakeClient(), DatabaseJobRepository(session))
    summary = service.ingest(keywords="Python Developer", location="Egypt", limit=2)

    assert summary.fetched == 2
    assert summary.created == 1
    assert summary.duplicates_skipped == 1


def test_ingestion_logs_extraction_failure_and_keeps_job(caplog):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    class FakeClient:
        def search(self, **kwargs):
            return [_raw()]

    class FailingPipeline:
        def extract(self, description):
            raise RuntimeError("provider quota exhausted")

    caplog.set_level("WARNING")
    service = JoobleIngestionService(FakeClient(), DatabaseJobRepository(session), FailingPipeline())
    summary = service.ingest(keywords="Python Developer", location="Egypt", limit=1)

    assert summary.extraction_failures == 1
    assert summary.created == 1
    assert "job_id=jooble:123" in caplog.text
    assert "source_external_id=123" in caplog.text
    assert "stage=job_extraction" in caplog.text
    assert session.query(JobRequirementModel).count() == 1


def test_ingestion_hands_normalized_description_to_existing_extractor():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    profile = JobRequirementProfile(
        canonical_role="Python Developer",
        required_skills=[
            NormalizedSkill(
                skill_id="skill_python",
                canonical_name="Python",
                raw_extracted="Python",
                importance="important",
            )
        ],
        extraction_confidence=0.35,
    )

    class FakeClient:
        def search(self, **kwargs):
            return [_raw()]

    class FakePipeline:
        def __init__(self):
            self.received = []

        def extract(self, description):
            self.received.append(description)
            return profile

    pipeline = FakePipeline()
    service = JoobleIngestionService(FakeClient(), DatabaseJobRepository(session), pipeline)
    summary = service.ingest(keywords="Python Developer", location="Egypt", limit=1)

    assert summary.extraction_successes == 1
    assert pipeline.received == ["Python developer needed"]
    stored = session.execute(text("SELECT structured_profile FROM jobs")).scalar_one()
    assert "Python Developer" in stored
