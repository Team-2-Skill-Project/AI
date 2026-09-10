import json
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from src.db.base import Base

class MatchRecordModel(Base):
    __tablename__ = "match_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(100), nullable=False, index=True)
    candidate_id = Column(String(100), nullable=False, index=True)
    overall_match_score = Column(Float, nullable=False)
    qualification_status = Column(String(50), nullable=False, index=True)
    full_candidate_summary = Column(Text, nullable=False)
    skill_breakdown_json = Column(Text, nullable=False)
    missing_critical_skills_json = Column(Text, nullable=False)
    recommended_upskilling_path_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "candidate_id": self.candidate_id,
            "overall_match_score": self.overall_match_score,
            "qualification_status": self.qualification_status,
            "full_candidate_summary": self.full_candidate_summary,
            "skill_breakdown": json.loads(self.skill_breakdown_json) if self.skill_breakdown_json else [],
            "missing_critical_skills": json.loads(self.missing_critical_skills_json) if self.missing_critical_skills_json else [],
            "recommended_upskilling_path": json.loads(self.recommended_upskilling_path_json) if self.recommended_upskilling_path_json else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
