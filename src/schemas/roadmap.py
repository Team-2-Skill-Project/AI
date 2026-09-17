from __future__ import annotations
"""Pydantic v2 output and request/response schemas for Feature 7: Dynamic Career Roadmap."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ResourceLinkSchema(BaseModel):
    type: str = Field(description="Type of resource (e.g., 'video', 'documentation')")
    url: str = Field(description="URL to the resource")
    title: str = Field(description="Title of the resource")
    thumbnail_url: Optional[str] = Field(default=None, description="Optional thumbnail URL for the resource")
    video_id: Optional[str] = Field(default=None, description="Optional YouTube video ID")


class RoadmapTask(BaseModel):
    task_id: str = Field(description="Unique task identifier")
    title: str = Field(description="Title of the learning or action item")
    description: Optional[str] = Field(default=None, description="Detailed guidance and instructions")
    estimated_hours: float = Field(default=2.0, description="Estimated time to complete in hours", ge=0.5)
    status: TaskStatus = Field(default=TaskStatus.NOT_STARTED, description="Current progress status")
    cited_gap: str = Field(description="The underlying skill gap this task addresses")
    resource_links: List[ResourceLinkSchema] = Field(default=[], description="Suggested learning resources")


class RoadmapMilestone(BaseModel):
    milestone_id: str = Field(description="Unique milestone identifier")
    title: str = Field(description="Milestone achievement title")
    target_week: int = Field(description="Target week number within the phase", ge=1)
    status: TaskStatus = Field(default=TaskStatus.NOT_STARTED, description="Overall milestone progress status")
    tasks: List[RoadmapTask] = Field(default=[], description="Action items required to fulfill this milestone")


class RoadmapPhase(BaseModel):
    phase_id: str = Field(description="Unique phase identifier")
    title: str = Field(description="Phase title (e.g. 'Core Fundamentals Mastery')")
    order: int = Field(description="Sequence order of the phase (1-indexed)", ge=1)
    cited_gap: str = Field(description="Primary skill gap targeted in this phase")
    rationale: str = Field(description="Explanation of why this phase is scheduled at this order")
    milestones: List[RoadmapMilestone] = Field(default=[], description="Sequenced milestones in this phase")


class RoadmapSchema(BaseModel):
    roadmap_id: str = Field(description="Unique roadmap identifier")
    candidate_id: str = Field(description="Candidate identifier")
    target_role: str = Field(description="Target job title or role")
    role_family: Optional[str] = Field(default="Engineering", description="High-level role family (Engineering, Data, Frontend, etc.)")
    phases: List[RoadmapPhase] = Field(default=[], description="Phases of the roadmap")
    total_weeks: int = Field(default=4, description="Total estimated duration in weeks", ge=1)
    created_at: Optional[str] = Field(default=None, description="ISO timestamp of creation")
    updated_at: Optional[str] = Field(default=None, description="ISO timestamp of last update")

    @field_validator("phases")
    @classmethod
    def validate_grounding(cls, phases: List[RoadmapPhase]) -> List[RoadmapPhase]:
        """Ensure every phase has a non-empty cited_gap."""
        for phase in phases:
            if not phase.cited_gap or not phase.cited_gap.strip():
                raise ValueError(f"Phase '{phase.title}' lacks an underlying cited skill gap.")
        return phases


class RoadmapGenerationRequest(BaseModel):
    candidate_id: str = Field(..., description="Candidate identifier")
    target_role: str = Field(..., description="Target job title or role")
    role_family: Optional[str] = Field(default="Engineering", description="Role family (e.g. 'Engineering', 'Data', 'Frontend')")
    skill_gaps: List[str] = Field(..., min_length=1, description="List of prioritized skill gaps to address")


class TaskCompletionRequest(BaseModel):
    candidate_id: str = Field(..., description="Candidate identifier")
    task_id: str = Field(..., description="Task ID to update")
    status: TaskStatus = Field(..., description="New status (not_started, in_progress, completed)")


class RoadmapRefreshRequest(BaseModel):
    candidate_id: str = Field(..., description="Candidate identifier")
    target_role: Optional[str] = Field(default=None, description="Updated target role if changed")
    role_family: Optional[str] = Field(default=None, description="Updated role family if changed")
    new_skill_gaps: Optional[List[str]] = Field(default=None, description="Updated list of skill gaps")
