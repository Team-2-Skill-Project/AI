from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.base import Base
import src.db.models.roadmap  # noqa: F401
from src.schemas.roadmap import (
    RoadmapGenerationRequest,
    RoadmapRefreshRequest,
    TaskStatus,
)
from src.services.roadmap_service import roadmap_service


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.mark.asyncio
async def test_roadmap_generation_and_persistence(test_db):
    request = RoadmapGenerationRequest(
        candidate_id="cand_test_101",
        target_role="Senior Backend Engineer",
        role_family="Backend Engineering",
        skill_gaps=["Docker", "Kubernetes", "Redis"],
    )

    roadmap = await roadmap_service.create_roadmap(request, db=test_db)

    assert roadmap.candidate_id == "cand_test_101"
    assert roadmap.target_role == "Senior Backend Engineer"
    assert len(roadmap.phases) == 3

    # Check grounding citation
    for phase in roadmap.phases:
        assert phase.cited_gap in ["Docker", "Kubernetes", "Redis"]

    # Verify retrieval from DB
    fetched = roadmap_service.get_candidate_roadmap("cand_test_101", db=test_db)
    assert fetched is not None
    assert fetched.candidate_id == "cand_test_101"
    assert len(fetched.phases) == 3


@pytest.mark.asyncio
async def test_task_status_state_machine(test_db):
    request = RoadmapGenerationRequest(
        candidate_id="cand_test_102",
        target_role="Data Engineer",
        role_family="Data",
        skill_gaps=["Apache Spark"],
    )
    roadmap = await roadmap_service.create_roadmap(request, db=test_db)

    task_id = roadmap.phases[0].milestones[0].tasks[0].task_id

    # Update status to in_progress
    updated = roadmap_service.update_task_progress(
        candidate_id="cand_test_102",
        task_id=task_id,
        new_status=TaskStatus.IN_PROGRESS,
        db=test_db,
    )
    assert updated.phases[0].milestones[0].status == TaskStatus.IN_PROGRESS

    # Complete all tasks in milestone
    for t in updated.phases[0].milestones[0].tasks:
        roadmap_service.update_task_progress(
            candidate_id="cand_test_102",
            task_id=t.task_id,
            new_status=TaskStatus.COMPLETED,
            db=test_db,
        )

    final_rm = roadmap_service.get_candidate_roadmap("cand_test_102", db=test_db)
    assert final_rm.phases[0].milestones[0].status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_roadmap_adaptation_refresh(test_db):
    request = RoadmapGenerationRequest(
        candidate_id="cand_test_103",
        target_role="Frontend Engineer",
        role_family="Frontend",
        skill_gaps=["TypeScript", "GraphQL"],
    )
    await roadmap_service.create_roadmap(request, db=test_db)

    # Refresh with new skill gaps
    refresh_req = RoadmapRefreshRequest(
        candidate_id="cand_test_103",
        new_skill_gaps=["Next.js", "Web Performance"],
    )
    refreshed = await roadmap_service.refresh_roadmap(refresh_req, db=test_db)

    assert refreshed.candidate_id == "cand_test_103"
    assert len(refreshed.phases) == 2
    cited_gaps = [p.cited_gap for p in refreshed.phases]
    assert "Next.js" in cited_gaps
    assert "Web Performance" in cited_gaps


@pytest.mark.asyncio
async def test_roadmap_enrichment(test_db):
    from src.db.models.skill_resource import SkillResourceModel
    
    # Insert a dummy resource
    resource = SkillResourceModel(
        skill_id="skill_docker",
        video_id="dummy_video_id_123",
        title="Docker Tutorial for Beginners",
        channel_name="Tech Channel",
        status="approved"
    )
    test_db.add(resource)
    test_db.commit()

    request = RoadmapGenerationRequest(
        candidate_id="cand_test_104",
        target_role="DevOps Engineer",
        role_family="DevOps",
        skill_gaps=["Docker"],
    )
    
    roadmap = await roadmap_service.create_roadmap(request, db=test_db)
    
    # Check if the resource was enriched
    found_resource = False
    for phase in roadmap.phases:
        for milestone in phase.milestones:
            for task in milestone.tasks:
                if any(link.video_id == "dummy_video_id_123" or link.url.endswith("dummy_video_id_123") for link in task.resource_links):
                    found_resource = True
                    break
    
    assert found_resource, "The roadmap should be enriched with the approved YouTube resource"
