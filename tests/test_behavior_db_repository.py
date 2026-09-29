"""Comprehensive tests for persistent candidate behavior, interaction tracking, and recommendation integration."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.core.config import settings
from src.db.base import Base
from src.db.models.candidate import CandidateModel
from src.db.models.job_requirement import JobRequirementModel
from src.db.repositories.behavior_repository import DatabaseBehaviorRepository
from src.models.candidate import (
    Candidate,
    CandidatePreferences,
    CandidateProfile,
    CandidateSkill,
    EvidenceItem,
    UserProfile,
)
from src.repositories.behavior_repository import behavior_repository, MockBehaviorRepository
from src.repositories.candidate_repository import candidate_repository
from src.schemas.job import JobPosting, SkillRequirement
from src.services.recommendation_scoring import calculate_behavior_score
from src.services.recommendation_service import RecommendationService, recommendation_service


@pytest.fixture
def isolated_db_session():
    """Provides an isolated SQLite memory database for behavior repository tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test_api_key")
    return {"X-API-Key": "test_api_key"}


@pytest.fixture
def test_client():
    return TestClient(app)


def _persist_interaction_entities(session, candidate_ids, job_ids):
    """Create the real parent records required by interaction persistence."""
    session.add_all(CandidateModel(id=candidate_id) for candidate_id in candidate_ids)
    session.add_all(JobRequirementModel(id=job_id, title=f"Test {job_id}") for job_id in job_ids)
    session.commit()


# ── 1. Persistence & Retrieval of Events ─────────────────────────────────────────

def test_behavior_persistence_and_retrieval(isolated_db_session):
    """Test recording view, click, save, apply, and dismiss events into database."""
    repo = DatabaseBehaviorRepository(isolated_db_session)

    cid = "cand_behavior_001"
    _persist_interaction_entities(isolated_db_session, [cid], ["job_101", "job_102", "job_103", "job_104"])
    repo.record_interaction(cid, "job_101", "view")
    repo.record_interaction(cid, "job_102", "save")
    repo.record_interaction(cid, "job_103", "apply")
    repo.record_interaction(cid, "job_104", "dismiss")

    behavior = repo.get_candidate_behavior(cid)
    assert behavior.viewed_job_ids == ["job_101"]
    assert behavior.saved_job_ids == ["job_102"]
    assert behavior.applied_job_ids == ["job_103"]
    assert behavior.dismissed_job_ids == ["job_104"]


# ── 2. Repeated Requests & State Consistency ────────────────────────────────────

def test_repeated_save_apply_dismiss_idempotency_and_state_consistency(isolated_db_session):
    """
    Test event consistency semantics:
      - Repeated saves do not duplicate in saved_job_ids.
      - Repeated applies do not duplicate in applied_job_ids.
      - Repeated dismisses do not duplicate in dismissed_job_ids.
      - Saving a dismissed job cancels the dismissal.
      - Dismissing a saved job cancels the save.
      - Applying to a saved or dismissed job marks it applied and cancels dismiss.
      - Dismissing an already-applied job does NOT remove its applied status.
    """
    repo = DatabaseBehaviorRepository(isolated_db_session)
    cid = "cand_idempotency_001"
    _persist_interaction_entities(isolated_db_session, [cid], ["job_A", "job_B"])

    # Repeated save
    repo.record_interaction(cid, "job_A", "save")
    repo.record_interaction(cid, "job_A", "save")
    repo.record_interaction(cid, "job_A", "save")
    behavior = repo.get_candidate_behavior(cid)
    assert behavior.saved_job_ids == ["job_A"]

    # Dismiss job_A -> cancels save
    repo.record_interaction(cid, "job_A", "dismiss")
    behavior = repo.get_candidate_behavior(cid)
    assert "job_A" not in behavior.saved_job_ids
    assert behavior.dismissed_job_ids == ["job_A"]

    # Re-save job_A -> cancels dismissal
    repo.record_interaction(cid, "job_A", "save")
    behavior = repo.get_candidate_behavior(cid)
    assert behavior.saved_job_ids == ["job_A"]
    assert "job_A" not in behavior.dismissed_job_ids

    # Apply to job_B repeatedly
    repo.record_interaction(cid, "job_B", "apply")
    repo.record_interaction(cid, "job_B", "apply")
    behavior = repo.get_candidate_behavior(cid)
    assert behavior.applied_job_ids == ["job_B"]

    # Trying to dismiss an already-applied job: applied status must be preserved
    repo.record_interaction(cid, "job_B", "dismiss")
    behavior = repo.get_candidate_behavior(cid)
    assert "job_B" in behavior.applied_job_ids
    assert "job_B" not in behavior.dismissed_job_ids


# ── 3. Multiple Views and Clicks ───────────────────────────────────────────────

def test_multiple_views_and_clicks(isolated_db_session):
    """View and click events may occur multiple times and are accurately tracked."""
    repo = DatabaseBehaviorRepository(isolated_db_session)
    cid = "cand_multi_clicks"
    jid = "job_popular"
    _persist_interaction_entities(isolated_db_session, [cid], [jid])

    repo.record_interaction(cid, jid, "view")
    repo.record_interaction(cid, jid, "view")
    repo.record_interaction(cid, jid, "click")
    repo.record_interaction(cid, jid, "click")
    repo.record_interaction(cid, jid, "view")

    counts = repo.get_interaction_counts(cid, jid)
    assert counts.get("view") == 3
    assert counts.get("click") == 2

    # In CandidateBehaviorHistory, viewed_job_ids contains the unique job ID once
    behavior = repo.get_candidate_behavior(cid)
    assert behavior.viewed_job_ids == [jid]


# ── 4. Candidate Isolation ──────────────────────────────────────────────────────

def test_candidate_behavior_isolation(isolated_db_session):
    """Candidate A and Candidate B behaviors must remain strictly isolated."""
    repo = DatabaseBehaviorRepository(isolated_db_session)
    cand_1 = "cand_isolation_1"
    cand_2 = "cand_isolation_2"
    _persist_interaction_entities(isolated_db_session, [cand_1, cand_2], ["job_shared"])

    repo.record_interaction(cand_1, "job_shared", "save")
    repo.record_interaction(cand_2, "job_shared", "dismiss")

    behavior_1 = repo.get_candidate_behavior(cand_1)
    behavior_2 = repo.get_candidate_behavior(cand_2)

    assert behavior_1.saved_job_ids == ["job_shared"]
    assert behavior_1.dismissed_job_ids == []

    assert behavior_2.dismissed_job_ids == ["job_shared"]
    assert behavior_2.saved_job_ids == []


# ── 5. Behavior Persistence After Session / Repository Restart ──────────────────

def test_behavior_survives_repository_restart(isolated_db_session):
    """Interactions must survive application or repository instance restart."""
    repo_first = DatabaseBehaviorRepository(isolated_db_session)
    cid = "cand_restart_test"
    _persist_interaction_entities(isolated_db_session, [cid], ["job_999", "job_888"])

    repo_first.record_interaction(cid, "job_999", "save")
    repo_first.record_interaction(cid, "job_888", "apply")

    # Simulate fresh repo instance connected to the same persistence engine
    repo_restarted = DatabaseBehaviorRepository(isolated_db_session)
    behavior = repo_restarted.get_candidate_behavior(cid)

    assert behavior.saved_job_ids == ["job_999"]
    assert behavior.applied_job_ids == ["job_888"]


# ── 6. Cold-Start Candidate Without Interactions ──────────────────────────────

def test_cold_start_candidate_without_interactions(isolated_db_session):
    """A new candidate with no history receives a clean empty history and neutral score."""
    repo = DatabaseBehaviorRepository(isolated_db_session)

    behavior = repo.get_candidate_behavior("cand_brand_new_zero_history")
    assert behavior.saved_job_ids == []
    assert behavior.applied_job_ids == []
    assert behavior.dismissed_job_ids == []
    assert behavior.viewed_job_ids == []

    # Scoring must yield neutral baseline (50.0) without fabricated records
    score = calculate_behavior_score(behavior, JobPosting(job_id="job_any", title="Any Job"))
    assert score == 50.0


def test_record_interaction_rejects_missing_parent_records(isolated_db_session):
    repo = DatabaseBehaviorRepository(isolated_db_session)
    _persist_interaction_entities(isolated_db_session, ["cand_exists"], ["job_exists"])

    with pytest.raises(LookupError, match="Candidate 'cand_missing' was not found"):
        repo.record_interaction("cand_missing", "job_exists", "view")
    with pytest.raises(LookupError, match="Job 'job_missing' was not found"):
        repo.record_interaction("cand_exists", "job_missing", "view")


# ── 7. Applied and Dismissed Job Filtering in RecommendationService ─────────────

def test_applied_and_dismissed_filtering_in_recommendation_service():
    """Verify applied and dismissed jobs are filtered out while saved jobs get score boost."""
    job_active = JobPosting(job_id="job_active_1", title="Backend Engineer")
    job_applied = JobPosting(job_id="job_applied_1", title="Backend Engineer")
    job_dismissed = JobPosting(job_id="job_dismissed_1", title="Backend Engineer")
    job_saved = JobPosting(job_id="job_saved_1", title="Backend Engineer")

    behavior = DatabaseBehaviorRepository.normalize_interaction_type("save")
    from src.schemas.recommendation import CandidateBehaviorHistory

    custom_behavior = CandidateBehaviorHistory(
        saved_job_ids=["job_saved_1"],
        applied_job_ids=["job_applied_1"],
        dismissed_job_ids=["job_dismissed_1"],
    )

    service = RecommendationService()
    filtered = service.filter_candidate_jobs(
        [job_active, job_applied, job_dismissed, job_saved],
        custom_behavior,
    )

    filtered_ids = {j.job_id for j in filtered}
    assert "job_active_1" in filtered_ids
    assert "job_saved_1" in filtered_ids
    assert "job_applied_1" not in filtered_ids
    assert "job_dismissed_1" not in filtered_ids

    # Saved job receives 100.0 behavior score boost
    assert calculate_behavior_score(custom_behavior, job_saved) == 100.0
    # Active unsaved job receives neutral 50.0
    assert calculate_behavior_score(custom_behavior, job_active) == 50.0


# ── 8. API Endpoint: POST /api/v1/recommendations/events ─────────────────────────

def test_api_event_recording_happy_path(test_client, auth_headers):
    """Test successfully recording interaction events through the HTTP API."""
    # 1. Setup real candidate in persistence
    cand = Candidate(
        candidate_id="cand_api_event_test",
        user=UserProfile(name="Event Tester", email="event@test.com"),
    )
    candidate_repository.save_candidate(cand)

    # 2. Setup real job in persistence
    job = JobPosting(
        job_id="job_api_event_test",
        title="Software Engineer",
        company="EventCorp",
        source_url="https://eventcorp.test/jobs/1",
    )
    recommendation_service.job_repo.upsert(job)

    # 3. Post 'save' event
    save_payload = {
        "candidate_id": "cand_api_event_test",
        "job_id": "job_api_event_test",
        "event_type": "save",
        "metadata": {"source_page": "feed_card"},
    }
    res_save = test_client.post("/api/v1/recommendations/events", json=save_payload, headers=auth_headers)
    assert res_save.status_code == 201
    data_save = res_save.json()
    assert data_save["success"] is True
    assert data_save["candidate_id"] == "cand_api_event_test"
    assert data_save["job_id"] == "job_api_event_test"
    assert data_save["event_type"] == "save"
    assert "recorded_at" in data_save

    # Verify persisted behavior reflects save
    behavior = recommendation_service.behavior_repo.get_candidate_behavior("cand_api_event_test")
    assert "job_api_event_test" in behavior.saved_job_ids

    # 4. Post 'view' event
    view_payload = {
        "candidate_id": "cand_api_event_test",
        "job_id": "job_api_event_test",
        "event_type": "view",
    }
    res_view = test_client.post("/api/v1/recommendations/events", json=view_payload, headers=auth_headers)
    assert res_view.status_code == 201
    assert res_view.json()["event_type"] == "view"


# ── 9. API Event Validation Errors ──────────────────────────────────────────────

def test_api_event_missing_candidate_returns_404(test_client, auth_headers):
    """Submitting event for non-existent candidate returns 404."""
    # Ensure job exists
    job = JobPosting(job_id="job_exists_for_404_test", title="Dev", company="C", source_url="https://c.test/1")
    recommendation_service.job_repo.upsert(job)

    payload = {
        "candidate_id": "cand_does_not_exist_at_all",
        "job_id": "job_exists_for_404_test",
        "event_type": "view",
    }
    response = test_client.post("/api/v1/recommendations/events", json=payload, headers=auth_headers)
    assert response.status_code == 404
    assert "cand_does_not_exist_at_all" in response.json().get("detail", "")


def test_api_event_missing_job_returns_404(test_client, auth_headers):
    """Submitting event for non-existent job returns 404."""
    # Ensure candidate exists
    cand = Candidate(candidate_id="cand_exists_for_404_test", user=UserProfile(name="Tester"))
    candidate_repository.save_candidate(cand)

    payload = {
        "candidate_id": "cand_exists_for_404_test",
        "job_id": "job_that_does_not_exist_xyz",
        "event_type": "view",
    }
    response = test_client.post("/api/v1/recommendations/events", json=payload, headers=auth_headers)
    assert response.status_code == 404
    assert "job_that_does_not_exist_xyz" in response.json().get("detail", "")


def test_api_event_invalid_event_type_returns_400(test_client, auth_headers):
    """Submitting unsupported event type returns 400."""
    cand = Candidate(candidate_id="cand_valid_for_400", user=UserProfile(name="Tester"))
    candidate_repository.save_candidate(cand)

    job = JobPosting(job_id="job_valid_for_400", title="Dev", company="C", source_url="https://c.test/2")
    recommendation_service.job_repo.upsert(job)

    payload = {
        "candidate_id": "cand_valid_for_400",
        "job_id": "job_valid_for_400",
        "event_type": "super_like_unsupported",
    }
    response = test_client.post("/api/v1/recommendations/events", json=payload, headers=auth_headers)
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "Unsupported interaction type" in detail


def test_api_event_missing_required_fields_returns_422(test_client, auth_headers):
    """Payloads missing candidate_id, job_id, or event_type return 422."""
    res_no_candidate = test_client.post(
        "/api/v1/recommendations/events",
        json={"job_id": "job_1", "event_type": "view"},
        headers=auth_headers,
    )
    assert res_no_candidate.status_code == 422

    res_no_job = test_client.post(
        "/api/v1/recommendations/events",
        json={"candidate_id": "cand_1", "event_type": "view"},
        headers=auth_headers,
    )
    assert res_no_job.status_code == 422

    res_no_type = test_client.post(
        "/api/v1/recommendations/events",
        json={"candidate_id": "cand_1", "job_id": "job_1"},
        headers=auth_headers,
    )
    assert res_no_type.status_code == 422


# ── 10. Runtime Default Verification ────────────────────────────────────────────

def test_runtime_uses_database_behavior_repository_by_default():
    """Verify RecommendationService default behavior_repo is the persistent repository."""
    service = RecommendationService()
    # Must delegate to DatabaseBehaviorRepository, not MockBehaviorRepository
    assert not isinstance(service.behavior_repo, MockBehaviorRepository)
    from src.db.repositories.behavior_repository import DatabaseBehaviorRepository
    assert isinstance(service.behavior_repo._get_delegate(), DatabaseBehaviorRepository)


def test_end_to_end_event_updates_feed_ranking_and_filtering(test_client, auth_headers):
    """
    End-to-end test proving that:
      1. Candidate initially sees both jobs.
      2. Posting a 'save' event gives that job an affinity boost and is_saved=True.
      3. Posting an 'apply' event completely excludes that job from the feed.
      4. Posting a 'dismiss' event completely excludes that job from the feed.
    """
    cid = "cand_e2e_behavior_flow"
    recommendation_service.behavior_repo.clear_candidate_interactions(cid)
    cand = Candidate(
        candidate_id=cid,
        user=UserProfile(name="E2E Flow Candidate"),
        candidate_skills=[
            CandidateSkill(skill_id="skill_python", name="Python", proficiency="expert"),
            CandidateSkill(skill_id="skill_fastapi", name="FastAPI", proficiency="expert"),
        ],
        target_roles=["Backend Engineer"],
    )
    candidate_repository.save_candidate(cand)

    job1 = JobPosting(
        job_id="job_e2e_flow_1",
        title="Backend Engineer",
        company="AlphaCorp",
        source_url="https://alpha.test/1",
        required_skills=[SkillRequirement(skill_name="Python", proficiency="Expert")],
    )
    job2 = JobPosting(
        job_id="job_e2e_flow_2",
        title="Backend Engineer",
        company="BetaCorp",
        source_url="https://beta.test/2",
        required_skills=[SkillRequirement(skill_name="FastAPI", proficiency="Expert")],
    )
    recommendation_service.job_repo.upsert(job1)
    recommendation_service.job_repo.upsert(job2)

    # 1. Initial feed: both jobs present
    res1 = test_client.get(f"/api/v1/recommendations/feed?candidate_id={cid}", headers=auth_headers)
    assert res1.status_code == 200
    feed1_ids = {r["job_id"] for r in res1.json()["recommendations"]}
    assert "job_e2e_flow_1" in feed1_ids
    assert "job_e2e_flow_2" in feed1_ids

    # 2. Candidate saves job2
    res_save = test_client.post(
        "/api/v1/recommendations/events",
        json={"candidate_id": cid, "job_id": "job_e2e_flow_2", "event_type": "save"},
        headers=auth_headers,
    )
    assert res_save.status_code == 201

    res2 = test_client.get(f"/api/v1/recommendations/feed?candidate_id={cid}", headers=auth_headers)
    assert res2.status_code == 200
    job2_rec = next(r for r in res2.json()["recommendations"] if r["job_id"] == "job_e2e_flow_2")
    assert job2_rec["is_saved"] is True
    assert job2_rec["score_breakdown"]["behavior_boost"] == 100.0

    # 3. Candidate applies to job1 -> job1 must be filtered out
    res_apply = test_client.post(
        "/api/v1/recommendations/events",
        json={"candidate_id": cid, "job_id": "job_e2e_flow_1", "event_type": "apply"},
        headers=auth_headers,
    )
    assert res_apply.status_code == 201

    res3 = test_client.get(f"/api/v1/recommendations/feed?candidate_id={cid}", headers=auth_headers)
    assert res3.status_code == 200
    feed3_ids = {r["job_id"] for r in res3.json()["recommendations"]}
    assert "job_e2e_flow_1" not in feed3_ids, "Applied job was not excluded from feed"
    assert "job_e2e_flow_2" in feed3_ids

    # 4. Candidate dismisses job2 -> job2 must be filtered out
    res_dismiss = test_client.post(
        "/api/v1/recommendations/events",
        json={"candidate_id": cid, "job_id": "job_e2e_flow_2", "event_type": "dismiss"},
        headers=auth_headers,
    )
    assert res_dismiss.status_code == 201

    res4 = test_client.get(f"/api/v1/recommendations/feed?candidate_id={cid}", headers=auth_headers)
    assert res4.status_code == 200
    feed4_ids = {r["job_id"] for r in res4.json()["recommendations"]}
    assert "job_e2e_flow_2" not in feed4_ids, "Dismissed job was not excluded from feed"


def test_api_key_auth_enforcement_on_events(monkeypatch):
    """When API Key authentication is enabled, unauthorized requests without key return 401."""
    from src.core.config import get_app_settings
    client = TestClient(app)

    # Temporarily enable API key authentication
    app_settings = get_app_settings()
    monkeypatch.setattr(app_settings, "enable_api_key_auth", True)
    monkeypatch.setattr(app_settings, "api_key", "secret_key_123")

    payload = {"candidate_id": "c1", "job_id": "j1", "event_type": "view"}

    # Without header -> 401 Unauthorized
    res_no_auth = client.post("/api/v1/recommendations/events", json=payload)
    assert res_no_auth.status_code == 401

    # With invalid key -> 401 Unauthorized
    res_wrong_key = client.post(
        "/api/v1/recommendations/events",
        json=payload,
        headers={"X-API-Key": "wrong_key"},
    )
    assert res_wrong_key.status_code == 401


def test_event_ingestion_is_unavailable_without_a_configured_service_key(monkeypatch):
    """The write endpoint must not become public when general API-key auth is disabled."""
    client = TestClient(app)
    monkeypatch.setattr(settings, "enable_api_key_auth", False)
    monkeypatch.setattr(settings, "api_key", None)

    response = client.post(
        "/api/v1/recommendations/events",
        json={"candidate_id": "c1", "job_id": "j1", "event_type": "view"},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "SERVICE_AUTH_NOT_CONFIGURED"
