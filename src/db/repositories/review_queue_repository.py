import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from src.db.models.review_queue import ReviewQueueModel
from src.db.repositories.base import BaseRepository

class ReviewQueueRepository(BaseRepository[ReviewQueueModel]):
    def __init__(self, db: Session):
        super().__init__(ReviewQueueModel, db)

    def enqueue(
        self,
        item_type: str,
        target_id: str,
        payload: Dict[str, Any],
        flagged_reasons: List[str],
        priority: str = "medium",
    ) -> ReviewQueueModel:
        """Adds an AI evaluation or decision to the shared review queue."""
        item = ReviewQueueModel(
            id=str(uuid.uuid4()),
            item_type=item_type,
            target_id=target_id,
            status="pending",
            priority=priority,
            flagged_reasons_json=json.dumps(flagged_reasons),
            payload_json=json.dumps(payload),
        )
        return self.create(item)

    def list_items(
        self,
        status: Optional[str] = None,
        item_type: Optional[str] = None,
        priority: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[ReviewQueueModel]:
        """Queries review items with flexible filtering for dashboards and Laravel sync."""
        query = self.db.query(ReviewQueueModel)
        if status:
            query = query.filter(ReviewQueueModel.status == status)
        if item_type:
            query = query.filter(ReviewQueueModel.item_type == item_type)
        if priority:
            query = query.filter(ReviewQueueModel.priority == priority)

        return query.order_by(ReviewQueueModel.created_at.desc()).offset(skip).limit(limit).all()

    def claim_item(self, item_id: str, reviewer_id: str) -> Optional[ReviewQueueModel]:
        """Assigns an item to a reviewer and sets status to in_review."""
        item = self.get_by_id(item_id)
        if not item:
            return None
        item.status = "in_review"
        item.reviewer_id = reviewer_id
        item.updated_at = datetime.utcnow()
        return self.update(item)

    def resolve_item(
        self,
        item_id: str,
        status: str,
        reviewer_notes: Optional[str] = None,
        resolution: Optional[Dict[str, Any]] = None,
        reviewer_id: Optional[str] = None,
    ) -> Optional[ReviewQueueModel]:
        """Resolves an item with approved/rejected/escalated verdict and notes."""
        item = self.get_by_id(item_id)
        if not item:
            return None
        item.status = status
        if reviewer_id:
            item.reviewer_id = reviewer_id
        if reviewer_notes is not None:
            item.reviewer_notes = reviewer_notes
        if resolution is not None:
            item.resolution_json = json.dumps(resolution)
        item.reviewed_at = datetime.utcnow()
        item.updated_at = datetime.utcnow()
        return self.update(item)
