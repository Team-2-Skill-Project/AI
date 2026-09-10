import json
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import Column, String, Text, DateTime
from src.db.base import Base

class ReviewQueueModel(Base):
    __tablename__ = "review_queue"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    item_type = Column(String(50), nullable=False, index=True)  # 'match_analysis', 'interview_evaluation'
    target_id = Column(String(100), nullable=False, index=True) # job_id, candidate_id, or session_id
    status = Column(String(30), default="pending", nullable=False, index=True) # 'pending', 'in_review', 'approved', 'rejected', 'escalated'
    priority = Column(String(20), default="medium", nullable=False, index=True) # 'low', 'medium', 'high', 'urgent'
    flagged_reasons_json = Column(Text, nullable=False, default="[]")
    payload_json = Column(Text, nullable=False)
    reviewer_id = Column(String(100), nullable=True)
    reviewer_notes = Column(Text, nullable=True)
    resolution_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "item_type": self.item_type,
            "target_id": self.target_id,
            "status": self.status,
            "priority": self.priority,
            "flagged_reasons": json.loads(self.flagged_reasons_json) if self.flagged_reasons_json else [],
            "payload": json.loads(self.payload_json) if self.payload_json else {},
            "reviewer_id": self.reviewer_id,
            "reviewer_notes": self.reviewer_notes,
            "resolution": json.loads(self.resolution_json) if self.resolution_json else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }
