from __future__ import annotations
import json
from typing import Optional
from sqlalchemy.orm import Session
from src.db.models.roadmap import RoadmapModel
from src.db.repositories.base import BaseRepository
from src.schemas.roadmap import RoadmapSchema


class RoadmapRepository(BaseRepository[RoadmapModel]):
    def __init__(self, db: Session):
        super().__init__(RoadmapModel, db)

    def get_by_candidate(self, candidate_id: str) -> Optional[RoadmapModel]:
        """Fetch the most recent active roadmap for a candidate."""
        return (
            self.db.query(RoadmapModel)
            .filter(RoadmapModel.candidate_id == candidate_id)
            .order_by(RoadmapModel.updated_at.desc())
            .first()
        )

    def save_roadmap(self, roadmap: RoadmapSchema) -> RoadmapModel:
        """Upsert candidate roadmap in the database."""
        existing = self.db.query(RoadmapModel).filter(
            (RoadmapModel.roadmap_id == roadmap.roadmap_id) | (RoadmapModel.candidate_id == roadmap.candidate_id)
        ).first()
        payload_str = json.dumps(roadmap.model_dump())

        if existing:
            existing.roadmap_id = roadmap.roadmap_id
            existing.candidate_id = roadmap.candidate_id
            existing.target_role = roadmap.target_role
            existing.role_family = roadmap.role_family
            existing.total_weeks = roadmap.total_weeks
            existing.payload_json = payload_str
            self.db.commit()
            self.db.refresh(existing)
            return existing

        record = RoadmapModel(
            roadmap_id=roadmap.roadmap_id,
            candidate_id=roadmap.candidate_id,
            target_role=roadmap.target_role,
            role_family=roadmap.role_family,
            total_weeks=roadmap.total_weeks,
            payload_json=payload_str,
        )
        return self.create(record)
