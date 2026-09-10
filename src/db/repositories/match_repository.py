import json
from typing import Optional, List
from sqlalchemy.orm import Session
from src.db.models.match import MatchRecordModel
from src.db.repositories.base import BaseRepository
from src.schemas.match import SkillGapAnalysisResponse

class MatchRepository(BaseRepository[MatchRecordModel]):
    def __init__(self, db: Session):
        super().__init__(MatchRecordModel, db)

    def save_match_result(self, match_res: SkillGapAnalysisResponse) -> MatchRecordModel:
        """Persists a calculated SkillGapAnalysisResponse into the database."""
        record = MatchRecordModel(
            job_id=match_res.job_id,
            candidate_id=match_res.candidate_id,
            overall_match_score=match_res.overall_match_score,
            qualification_status=str(match_res.qualification_status),
            full_candidate_summary=match_res.full_candidate_summary,
            skill_breakdown_json=json.dumps([item.model_dump() for item in match_res.skill_breakdown]),
            missing_critical_skills_json=json.dumps(match_res.missing_critical_skills),
            recommended_upskilling_path_json=json.dumps(match_res.recommended_upskilling_path),
        )
        return self.create(record)

    def get_latest_match(self, job_id: str, candidate_id: str) -> Optional[MatchRecordModel]:
        """Finds the most recent match evaluation between a specific job and candidate."""
        return (
            self.db.query(MatchRecordModel)
            .filter(
                MatchRecordModel.job_id == job_id,
                MatchRecordModel.candidate_id == candidate_id
            )
            .order_by(MatchRecordModel.created_at.desc())
            .first()
        )

    def list_by_job(self, job_id: str, skip: int = 0, limit: int = 50) -> List[MatchRecordModel]:
        return (
            self.db.query(MatchRecordModel)
            .filter(MatchRecordModel.job_id == job_id)
            .order_by(MatchRecordModel.overall_match_score.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_candidate(self, candidate_id: str, skip: int = 0, limit: int = 50) -> List[MatchRecordModel]:
        return (
            self.db.query(MatchRecordModel)
            .filter(MatchRecordModel.candidate_id == candidate_id)
            .order_by(MatchRecordModel.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
