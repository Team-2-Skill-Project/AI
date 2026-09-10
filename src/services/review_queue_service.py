import logging
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from src.db.repositories.review_queue_repository import ReviewQueueRepository
from src.schemas.match import SkillGapAnalysisResponse
from src.schemas.interview import AnswerEvaluationResponse
from src.schemas.review_queue import (
    ReviewQueueItemResponse,
    ReviewQueueListResponse,
    ReviewResolutionRequest,
)

logger = logging.getLogger(__name__)

class ReviewQueueService:
    """
    Manages the shared human-in-the-loop review queue for AI evaluations.
    Detects borderline decisions, flags security risks, and coordinates reviewer assignments.
    """

    @staticmethod
    def should_flag_match(response: SkillGapAnalysisResponse) -> Tuple[bool, List[str], str]:
        """
        Determines whether a skill gap assessment requires human recruiter review.
        Returns: (needs_review, flagged_reasons, priority)
        """
        reasons: List[str] = []
        priority = "medium"

        # 1. Borderline score range (between 45 and 75)
        if 45.0 <= response.overall_match_score < 75.0:
            reasons.append(f"Borderline match score ({response.overall_match_score:.1f}/100)")
            priority = "high"

        # 2. Partially Qualified status
        if response.qualification_status == "Partially Qualified":
            reasons.append("Status is 'Partially Qualified' - requires recruiter discretion on upskilling viability.")
            priority = "high"

        # 3. High overall score but critical skills missing
        if response.overall_match_score >= 70.0 and len(response.missing_critical_skills) > 0:
            reasons.append(
                f"Candidate scored high ({response.overall_match_score:.1f}) but failed critical skills: "
                f"{', '.join(response.missing_critical_skills)}"
            )
            priority = "urgent"

        needs_review = len(reasons) > 0
        return needs_review, reasons, priority

    @staticmethod
    def should_flag_interview(eval_res: AnswerEvaluationResponse) -> Tuple[bool, List[str], str]:
        """
        Determines whether an interview answer evaluation requires audit/review.
        """
        reasons: List[str] = []
        priority = "medium"

        if eval_res.security_assessment and eval_res.security_assessment.has_security_vulnerabilities:
            reasons.append("Security vulnerabilities identified in candidate's answer.")
            priority = "urgent"

        if eval_res.security_assessment and eval_res.security_assessment.security_score < 6:
            reasons.append(f"Low security posture score: {eval_res.security_assessment.security_score}/10.")
            if priority != "urgent":
                priority = "high"

        if eval_res.score <= 3:
            reasons.append(f"Critically low technical score: {eval_res.score}/10.")

        needs_review = len(reasons) > 0
        return needs_review, reasons, priority

    def enqueue_match_if_needed(
        self,
        response: SkillGapAnalysisResponse,
        db: Session,
        force: bool = False
    ) -> Optional[ReviewQueueItemResponse]:
        """Auto-evaluates and enqueues a match result if it meets review criteria."""
        needs_review, reasons, priority = self.should_flag_match(response)
        if not needs_review and not force:
            return None

        if force and not reasons:
            reasons = ["Manually flagged for human recruiter review."]

        repo = ReviewQueueRepository(db)
        record = repo.enqueue(
            item_type="match_analysis",
            target_id=f"{response.job_id}:{response.candidate_id}",
            payload=response.model_dump(),
            flagged_reasons=reasons,
            priority=priority,
        )
        logger.info(f"Enqueued match analysis to review queue: item_id={record.id}, priority={priority}")
        return ReviewQueueItemResponse(**record.to_dict())

    def list_queue(
        self,
        db: Session,
        status: Optional[str] = None,
        item_type: Optional[str] = None,
        priority: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> ReviewQueueListResponse:
        repo = ReviewQueueRepository(db)
        records = repo.list_items(status=status, item_type=item_type, priority=priority, skip=skip, limit=limit)
        items = [ReviewQueueItemResponse(**r.to_dict()) for r in records]
        return ReviewQueueListResponse(items=items, total=len(items))

    def get_item(self, item_id: str, db: Session) -> Optional[ReviewQueueItemResponse]:
        repo = ReviewQueueRepository(db)
        record = repo.get_by_id(item_id)
        return ReviewQueueItemResponse(**record.to_dict()) if record else None

    def claim_item(self, item_id: str, reviewer_id: str, db: Session) -> Optional[ReviewQueueItemResponse]:
        repo = ReviewQueueRepository(db)
        record = repo.claim_item(item_id, reviewer_id)
        return ReviewQueueItemResponse(**record.to_dict()) if record else None

    def resolve_item(
        self,
        item_id: str,
        req: ReviewResolutionRequest,
        db: Session
    ) -> Optional[ReviewQueueItemResponse]:
        repo = ReviewQueueRepository(db)
        resolution_data = {
            "adjusted_score": req.adjusted_score,
            "adjusted_qualification_status": req.adjusted_qualification_status,
            "metadata": req.resolution_metadata,
        }
        record = repo.resolve_item(
            item_id=item_id,
            status=req.status,
            reviewer_notes=req.reviewer_notes,
            resolution=resolution_data,
            reviewer_id=req.reviewer_id,
        )
        return ReviewQueueItemResponse(**record.to_dict()) if record else None

review_queue_service = ReviewQueueService()
