from __future__ import annotations
import re
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
# pyrefly: ignore [missing-import]
from src.ai.factories.roadmap_factory import RoadmapChainFactory
# pyrefly: ignore [missing-import]
from src.db.base import SessionLocal
# pyrefly: ignore [missing-import]
from src.db.repositories.roadmap_repository import RoadmapRepository

# pyrefly: ignore [missing-import]
from src.schemas.roadmap import (
    RoadmapGenerationRequest,
    RoadmapRefreshRequest,
    RoadmapSchema,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class RoadmapService:
    """Service handling Roadmap generation, progress state machine, and adaptive updates."""

    async def create_roadmap(
        self,
        payload: RoadmapGenerationRequest,
        db: Optional[Session] = None,
    ) -> RoadmapSchema:
        chain = RoadmapChainFactory.for_role_family(
            role_family=payload.role_family or "Engineering"
        )
        roadmap = await chain.generate_roadmap(
            candidate_id=payload.candidate_id,
            target_role=payload.target_role,
            skill_gaps=payload.skill_gaps,
            role_family=payload.role_family,
        )

        # Persist to database
        session = db or SessionLocal()
        should_close = db is None
        try:
            repo = RoadmapRepository(session)
            repo.save_roadmap(roadmap)
            return self._enrich_roadmap_with_resources(roadmap, session)
        except Exception as err:
            logger.error("Failed to persist generated roadmap: %s", err, exc_info=True)
            return roadmap
        finally:
            if should_close:
                session.close()

    def get_candidate_roadmap(
        self,
        candidate_id: str,
        db: Optional[Session] = None,
    ) -> Optional[RoadmapSchema]:
        session = db or SessionLocal()
        should_close = db is None
        try:
            repo = RoadmapRepository(session)
            record = repo.get_by_candidate(candidate_id)
            if not record:
                return None
            roadmap = RoadmapSchema(**record.to_dict())
            return self._enrich_roadmap_with_resources(roadmap, session)
        finally:
            if should_close:
                session.close()

    def _enrich_roadmap_with_resources(self, roadmap: RoadmapSchema, session: Session) -> RoadmapSchema:
        try:
            # pyrefly: ignore [missing-import]
            from src.db.models.skill_resource import SkillResourceModel
            # pyrefly: ignore [missing-import]
            from src.taxonomy.taxonomy_manager import TaxonomyManager
            # pyrefly: ignore [missing-import]
            from src.schemas.roadmap import ResourceLinkSchema
            
            taxonomy = TaxonomyManager()
            for phase in roadmap.phases:
                for milestone in phase.milestones:
                    for task in milestone.tasks:
                        gap_query = task.cited_gap
                        skill_id, _, _ = taxonomy.normalize_skill(gap_query, strict=False)
                        
                        # If strict taxonomy matching fails, clean up the gap string (e.g. "Redis Caching & Pub/Sub" -> "Redis")
                        if not skill_id and ("&" in gap_query or "/" in gap_query or " " in gap_query):
                            first_keyword = re.split(r"[&/,]", gap_query)[0].strip()
                            skill_id, _, _ = taxonomy.normalize_skill(first_keyword, strict=False)

                        resources = []
                        if skill_id:
                            resources = session.query(SkillResourceModel).filter(
                                SkillResourceModel.skill_id == skill_id,
                                SkillResourceModel.status == "approved"
                            ).all()
                            
                        # If DB has approved resources for this skill_id, attach them
                        if resources:
                            for res in resources:
                                link = ResourceLinkSchema(
                                    type="video",
                                    url=f"https://www.youtube.com/watch?v={res.video_id}",
                                    title=res.title,
                                    thumbnail_url=res.thumbnail_url,
                                    video_id=res.video_id,
                                )
                                if not any(existing.url == link.url for existing in task.resource_links):
                                    task.resource_links.append(link)
                        else:
                            # Fallback: Live DuckDuckGo search for YouTube video tutorials
                            from src.workers.youtube_fetcher import fetch_from_duckduckgo
                            ddg_items = fetch_from_duckduckgo(gap_query, max_results=2)
                            for item in ddg_items:
                                link = ResourceLinkSchema(
                                    type="video",
                                    url=item.get("url", f"https://www.youtube.com/watch?v={item['video_id']}"),
                                    title=item["title"],
                                    thumbnail_url=item.get("thumbnail_url"),
                                    video_id=item["video_id"],
                                )
                                if not any(existing.url == link.url for existing in task.resource_links):
                                    task.resource_links.append(link)
                                
                                # Optionally cache into DB for future requests
                                try:
                                    existing_res = session.query(SkillResourceModel).filter(
                                        SkillResourceModel.video_id == item["video_id"]
                                    ).first()
                                    if not existing_res:
                                        new_res = SkillResourceModel(
                                            skill_id=skill_id or f"skill_{abs(hash(gap_query)) % 1000000}",
                                            video_id=item["video_id"],
                                            title=item["title"],
                                            channel_name=item.get("channel_name", "YouTube"),
                                            thumbnail_url=item.get("thumbnail_url"),
                                            status="approved"
                                        )
                                        session.add(new_res)
                                        session.commit()
                                except Exception:
                                    session.rollback()
        except Exception as e:
            logger.error(f"Error enriching roadmap with resources: {e}")
        
        return roadmap

    def update_task_progress(
        self,
        candidate_id: str,
        task_id: str,
        new_status: TaskStatus,
        db: Optional[Session] = None,
    ) -> RoadmapSchema:
        session = db or SessionLocal()
        should_close = db is None
        try:
            repo = RoadmapRepository(session)
            record = repo.get_by_candidate(candidate_id)
            if not record:
                raise ValueError(f"No active roadmap found for candidate '{candidate_id}'.")

            roadmap = RoadmapSchema(**record.to_dict())
            task_found = False

            for phase in roadmap.phases:
                for milestone in phase.milestones:
                    for task in milestone.tasks:
                        if task.task_id == task_id:
                            task.status = new_status
                            task_found = True

                    # Recalculate milestone status based on its tasks
                    all_tasks = milestone.tasks
                    if all_tasks:
                        if all(t.status == TaskStatus.COMPLETED for t in all_tasks):
                            milestone.status = TaskStatus.COMPLETED
                        elif any(t.status in (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED) for t in all_tasks):
                            milestone.status = TaskStatus.IN_PROGRESS
                        else:
                            milestone.status = TaskStatus.NOT_STARTED

            if not task_found:
                raise ValueError(f"Task '{task_id}' not found in candidate roadmap.")

            roadmap.updated_at = datetime.utcnow().isoformat()
            repo.save_roadmap(roadmap)
            return roadmap
        finally:
            if should_close:
                session.close()

    async def refresh_roadmap(
        self,
        payload: RoadmapRefreshRequest,
        db: Optional[Session] = None,
    ) -> RoadmapSchema:
        session = db or SessionLocal()
        should_close = db is None
        try:
            repo = RoadmapRepository(session)
            existing_record = repo.get_by_candidate(payload.candidate_id)

            if not existing_record:
                # If no existing roadmap exists, generate a new one
                target_role = payload.target_role or "Software Engineer"
                gaps = payload.new_skill_gaps or ["Core Fundamentals"]
                return await self.create_roadmap(
                    RoadmapGenerationRequest(
                        candidate_id=payload.candidate_id,
                        target_role=target_role,
                        role_family=payload.role_family or "Engineering",
                        skill_gaps=gaps,
                    ),
                    db=session,
                )

            existing_roadmap = RoadmapSchema(**existing_record.to_dict())

            # Identify completed task IDs and skill gaps already fulfilled
            completed_gaps = set()
            for phase in existing_roadmap.phases:
                for ms in phase.milestones:
                    if all(t.status == TaskStatus.COMPLETED for t in ms.tasks):
                        completed_gaps.add(phase.cited_gap)

            updated_role = payload.target_role or existing_roadmap.target_role
            updated_family = payload.role_family or existing_roadmap.role_family

            if payload.new_skill_gaps is not None:
                remaining_gaps = [g for g in payload.new_skill_gaps if g not in completed_gaps]
            else:
                remaining_gaps = [p.cited_gap for p in existing_roadmap.phases if p.cited_gap not in completed_gaps]

            if not remaining_gaps:
                remaining_gaps = ["Advanced Career Progression"]

            new_roadmap = await self.create_roadmap(
                RoadmapGenerationRequest(
                    candidate_id=payload.candidate_id,
                    target_role=updated_role,
                    role_family=updated_family,
                    skill_gaps=remaining_gaps,
                ),
                db=session,
            )

            return new_roadmap
        finally:
            if should_close:
                session.close()


roadmap_service = RoadmapService()
