from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict
from sqlalchemy import Column, DateTime, Integer, String, Text
# pyrefly: ignore [missing-import]
from src.db.base import Base


class RoadmapModel(Base):
    __tablename__ = "roadmaps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    roadmap_id = Column(String(100), unique=True, nullable=False, index=True)
    candidate_id = Column(String(100), nullable=False, index=True)
    target_role = Column(String(150), nullable=False)
    role_family = Column(String(100), nullable=True)
    total_weeks = Column(Integer, default=4, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        data = json.loads(self.payload_json) if self.payload_json else {}
        data["id"] = self.id
        data["roadmap_id"] = self.roadmap_id
        data["candidate_id"] = self.candidate_id
        data["target_role"] = self.target_role
        data["role_family"] = self.role_family
        data["total_weeks"] = self.total_weeks
        data["created_at"] = self.created_at.isoformat() if self.created_at else None
        data["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return data
