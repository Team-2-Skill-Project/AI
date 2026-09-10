from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

class ReviewQueueItemResponse(BaseModel):
    id: str = Field(description="Unique identifier of the review queue item")
    item_type: str = Field(description="Type of item (e.g. 'match_analysis', 'interview_evaluation')")
    target_id: str = Field(description="Target entity ID (job_id, candidate_id, or session_id)")
    status: str = Field(description="Status: 'pending', 'in_review', 'approved', 'rejected', 'escalated'")
    priority: str = Field(description="Priority level: 'low', 'medium', 'high', 'urgent'")
    flagged_reasons: List[str] = Field(default=[], description="Reasons this item was queued for human review")
    payload: Dict[str, Any] = Field(description="Full AI evaluation payload under review")
    reviewer_id: Optional[str] = Field(default=None, description="Identifier of the assigned human reviewer")
    reviewer_notes: Optional[str] = Field(default=None, description="Reviewer feedback and rationale")
    resolution: Optional[Dict[str, Any]] = Field(default=None, description="Outcome resolution details")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    reviewed_at: Optional[str] = None

class ReviewClaimRequest(BaseModel):
    reviewer_id: str = Field(description="Identifier or name of the reviewer claiming this task")

class ReviewResolutionRequest(BaseModel):
    status: Literal["approved", "rejected", "escalated"] = Field(
        description="Final verdict: approved, rejected, or escalated"
    )
    reviewer_id: Optional[str] = Field(default=None, description="Identifier of the reviewer")
    reviewer_notes: Optional[str] = Field(default=None, description="Mandatory or recommended reasoning")
    adjusted_score: Optional[float] = Field(default=None, description="Optional adjusted score if reviewer overrides AI")
    adjusted_qualification_status: Optional[str] = Field(
        default=None,
        description="Optional adjusted qualification status (e.g. 'Qualified', 'Partially Qualified')"
    )
    resolution_metadata: Dict[str, Any] = Field(default={}, description="Additional metadata for Laravel sync")

class ReviewQueueListResponse(BaseModel):
    items: List[ReviewQueueItemResponse]
    total: int
