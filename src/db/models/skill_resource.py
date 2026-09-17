from __future__ import annotations
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String
from src.db.base import Base

class SkillResourceModel(Base):
    __tablename__ = "skill_resources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_id = Column(String(100), index=True, nullable=False)
    video_id = Column(String(100), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    channel_name = Column(String(255), nullable=True)
    thumbnail_url = Column(String(500), nullable=True)
    duration = Column(String(50), nullable=True)
    status = Column(String(50), default="pending_review", nullable=False)  # pending_review, approved, rejected
    last_refreshed = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "skill_id": self.skill_id,
            "video_id": self.video_id,
            "title": self.title,
            "channel_name": self.channel_name,
            "thumbnail_url": self.thumbnail_url,
            "duration": self.duration,
            "status": self.status,
            "last_refreshed": self.last_refreshed.isoformat() if self.last_refreshed else None,
        }
