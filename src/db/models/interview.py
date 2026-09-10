import json
import uuid
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy import Column, String, Integer, Text, DateTime
from src.db.base import Base

class InterviewSessionModel(Base):
    __tablename__ = "interview_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(100), nullable=False, index=True)
    candidate_id = Column(String(100), nullable=False, index=True)
    target_role = Column(String(150), nullable=False)
    questions_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "candidate_id": self.candidate_id,
            "target_role": self.target_role,
            "questions": json.loads(self.questions_json) if self.questions_json else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class InterviewAnswerEvaluationModel(Base):
    __tablename__ = "interview_answer_evaluations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), nullable=True, index=True)
    question_id = Column(String(100), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    strengths_json = Column(Text, nullable=False)
    improvements_json = Column(Text, nullable=False)
    ideal_answer_outline = Column(Text, nullable=False)
    security_assessment_json = Column(Text, nullable=True)
    recommended_action = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "question_id": self.question_id,
            "score": self.score,
            "strengths": json.loads(self.strengths_json) if self.strengths_json else [],
            "improvements": json.loads(self.improvements_json) if self.improvements_json else [],
            "ideal_answer_outline": self.ideal_answer_outline,
            "security_assessment": json.loads(self.security_assessment_json) if self.security_assessment_json else None,
            "recommended_action": self.recommended_action,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
