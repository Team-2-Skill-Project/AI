import json
import uuid
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from src.db.models.interview import InterviewSessionModel, InterviewAnswerEvaluationModel
from src.db.repositories.base import BaseRepository
from src.schemas.interview import QuestionSetResponse, AnswerEvaluationResponse

class InterviewRepository(BaseRepository[InterviewSessionModel]):
    def __init__(self, db: Session):
        super().__init__(InterviewSessionModel, db)

    def save_session(self, session_res: QuestionSetResponse, candidate_id: str) -> InterviewSessionModel:
        """Persists generated interview questions session."""
        record = InterviewSessionModel(
            id=str(uuid.uuid4()),
            job_id=session_res.job_id,
            candidate_id=candidate_id,
            target_role=session_res.target_role,
            questions_json=json.dumps([q.model_dump() for q in session_res.questions]),
        )
        return self.create(record)

    def save_answer_evaluation(
        self,
        eval_res: AnswerEvaluationResponse,
        session_id: Optional[str] = None
    ) -> InterviewAnswerEvaluationModel:
        """Persists single question answer evaluation & security assessment."""
        sec_dict = eval_res.security_assessment.model_dump() if eval_res.security_assessment else None
        record = InterviewAnswerEvaluationModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            question_id=eval_res.question_id,
            score=eval_res.score,
            strengths_json=json.dumps(eval_res.strengths),
            improvements_json=json.dumps(eval_res.improvements),
            ideal_answer_outline=eval_res.ideal_answer_outline,
            security_assessment_json=json.dumps(sec_dict) if sec_dict else None,
            recommended_action=eval_res.recommended_action,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record
