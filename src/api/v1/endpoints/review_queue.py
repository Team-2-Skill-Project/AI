from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from src.db.base import get_db
from src.schemas.review_queue import (
    ReviewQueueItemResponse,
    ReviewQueueListResponse,
    ReviewClaimRequest,
    ReviewResolutionRequest,
)
from src.services.review_queue_service import review_queue_service

router = APIRouter(prefix="/review-queue", tags=["Shared Review Queue"])

@router.get(
    "/",
    response_model=ReviewQueueListResponse,
    status_code=status.HTTP_200_OK,
    summary="List review queue items"
)
def list_review_queue(
    status: Optional[str] = Query(None, description="Filter by status ('pending', 'in_review', 'approved', 'rejected')"),
    item_type: Optional[str] = Query(None, description="Filter by item_type ('match_analysis', 'interview_evaluation')"),
    priority: Optional[str] = Query(None, description="Filter by priority ('low', 'medium', 'high', 'urgent')"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
) -> ReviewQueueListResponse:
    """Returns paginated and filtered items awaiting human recruiter review."""
    return review_queue_service.list_queue(
        db=db,
        status=status,
        item_type=item_type,
        priority=priority,
        skip=skip,
        limit=limit
    )

@router.get(
    "/{item_id}",
    response_model=ReviewQueueItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single review queue item"
)
def get_review_queue_item(
    item_id: str,
    db: Session = Depends(get_db)
) -> ReviewQueueItemResponse:
    item = review_queue_service.get_item(item_id, db)
    if not item:
        raise HTTPException(status_code=404, detail=f"Review queue item '{item_id}' not found.")
    return item

@router.post(
    "/{item_id}/claim",
    response_model=ReviewQueueItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Claim item for review"
)
def claim_review_queue_item(
    item_id: str,
    payload: ReviewClaimRequest,
    db: Session = Depends(get_db)
) -> ReviewQueueItemResponse:
    item = review_queue_service.claim_item(item_id, payload.reviewer_id, db)
    if not item:
        raise HTTPException(status_code=404, detail=f"Review queue item '{item_id}' not found.")
    return item

@router.post(
    "/{item_id}/resolve",
    response_model=ReviewQueueItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve review item"
)
def resolve_review_queue_item(
    item_id: str,
    payload: ReviewResolutionRequest,
    db: Session = Depends(get_db)
) -> ReviewQueueItemResponse:
    item = review_queue_service.resolve_item(item_id, payload, db)
    if not item:
        raise HTTPException(status_code=404, detail=f"Review queue item '{item_id}' not found.")
    return item
