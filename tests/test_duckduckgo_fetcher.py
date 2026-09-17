from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.base import Base
import src.db.models.skill_resource  # noqa: F401
import src.db.models.review_queue  # noqa: F401
from src.workers.youtube_fetcher import fetch_from_duckduckgo
from src.db.repositories.review_queue_repository import ReviewQueueRepository
from src.services.review_queue_service import review_queue_service
from src.schemas.review_queue import ReviewResolutionRequest
from src.services.roadmap_service import roadmap_service
from src.schemas.roadmap import RoadmapGenerationRequest


def test_duckduckgo_fetch_rag():
    """Unit test to check if DuckDuckGo search returns valid YouTube links for 'RAG'."""
    results = fetch_from_duckduckgo("RAG", max_results=3)
    
    assert isinstance(results, list)
    assert len(results) > 0, "DuckDuckGo should return at least 1 video result for 'RAG'"
    
    for item in results:
        assert "video_id" in item and item["video_id"]
        assert "title" in item and item["title"]
        assert "url" in item and "youtube.com" in item["url"]
        assert "thumbnail_url" in item and item["thumbnail_url"]


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
async def test_rag_roadmap_integration_with_duckduckgo(test_db):
    """Integration test: fetch RAG resources via DuckDuckGo, approve in review queue, generate roadmap with RAG gap."""
    # 1. Fetch RAG videos from DuckDuckGo
    results = fetch_from_duckduckgo("RAG", max_results=2)
    assert len(results) > 0, "Should fetch at least 1 RAG video from DuckDuckGo"
    
    # 2. Push to review queue & approve
    review_repo = ReviewQueueRepository(test_db)
    
    for item in results:
        payload = {
            "skill_id": "skill_rag",
            "video_id": item["video_id"],
            "title": item["title"],
            "channel_name": item["channel_name"],
            "thumbnail_url": item["thumbnail_url"],
            "duration": item.get("duration", "N/A"),
            "url": item["url"]
        }
        review_item = review_repo.enqueue(
            item_type="youtube_resource",
            target_id="skill_rag",
            payload=payload,
            flagged_reasons=["Test DDG RAG fetch"],
            priority="medium"
        )
        
        # Admin approves the item
        resolution_req = ReviewResolutionRequest(
            status="approved",
            reviewer_notes="Approved RAG resource from test",
            reviewer_id="test_admin"
        )
        review_queue_service.resolve_item(review_item.id, req=resolution_req, db=test_db)

    # 3. Create a roadmap with skill gap RAG
    request = RoadmapGenerationRequest(
        candidate_id="cand_rag_user",
        target_role="AI / LLM Engineer",
        role_family="AI",
        skill_gaps=["RAG"],
    )
    
    roadmap = await roadmap_service.create_roadmap(request, db=test_db)
    
    # 4. Verify that RAG tasks contain YouTube links from DuckDuckGo
    found_rag_link = False
    for phase in roadmap.phases:
        for milestone in phase.milestones:
            for task in milestone.tasks:
                for link in task.resource_links:
                    if link.type == "video" and "youtube.com" in link.url:
                        found_rag_link = True
                        break
                        
    assert found_rag_link, "Roadmap for RAG gap should be enriched with DuckDuckGo YouTube tutorial link"
