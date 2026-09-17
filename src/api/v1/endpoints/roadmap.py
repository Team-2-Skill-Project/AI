from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.db.base import get_db
from src.schemas.roadmap import (
    RoadmapGenerationRequest,
    RoadmapRefreshRequest,
    RoadmapSchema,
    TaskCompletionRequest,
)
from src.services.roadmap_service import roadmap_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/roadmap", tags=["Dynamic Career Roadmap"])


@router.post(
    "/generate",
    response_model=RoadmapSchema,
    status_code=status.HTTP_200_OK,
    summary="Generate Dynamic Career Roadmap",
    description=(
        "Converts candidate skill gaps and target role metadata into a sequenced, "
        "multi-phase learning roadmap with milestones, weekly tasks, and cited gap grounding."
    ),
)
async def generate_roadmap(
    payload: RoadmapGenerationRequest,
    db: Session = Depends(get_db),
) -> RoadmapSchema:
    try:
        return await roadmap_service.create_roadmap(payload, db=db)
    except Exception as exc:
        logger.error("Failed to generate roadmap for candidate %s: %s", payload.candidate_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Roadmap generation failed: {exc!s}",
        ) from exc


@router.get(
    "/{candidate_id}",
    response_model=RoadmapSchema,
    status_code=status.HTTP_200_OK,
    summary="Get Active Candidate Roadmap",
    description="Fetches the current active dynamic career roadmap for a given candidate ID.",
)
def get_roadmap(
    candidate_id: str,
    db: Session = Depends(get_db),
) -> RoadmapSchema:
    roadmap = roadmap_service.get_candidate_roadmap(candidate_id, db=db)
    if not roadmap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active roadmap found for candidate '{candidate_id}'.",
        )
    return roadmap


@router.post(
    "/tasks/{task_id}/complete",
    response_model=RoadmapSchema,
    status_code=status.HTTP_200_OK,
    summary="Update Roadmap Task Progress",
    description="Updates the status (not_started, in_progress, completed) of a task and recalculates milestone completion.",
)
def complete_task(
    task_id: str,
    payload: TaskCompletionRequest,
    db: Session = Depends(get_db),
) -> RoadmapSchema:
    try:
        return roadmap_service.update_task_progress(
            candidate_id=payload.candidate_id,
            task_id=task_id,
            new_status=payload.status,
            db=db,
        )
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve)) from ve
    except Exception as exc:
        logger.error("Failed to update task progress for task %s: %s", task_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update task status: {exc!s}",
        ) from exc


@router.post(
    "/refresh",
    response_model=RoadmapSchema,
    status_code=status.HTTP_200_OK,
    summary="Refresh Dynamic Roadmap Priorities",
    description="Recomputes roadmap priorities for new skill gaps or target role changes while preserving completed milestones.",
)
async def refresh_roadmap(
    payload: RoadmapRefreshRequest,
    db: Session = Depends(get_db),
) -> RoadmapSchema:
    try:
        return await roadmap_service.refresh_roadmap(payload, db=db)
    except Exception as exc:
        logger.error("Failed to refresh roadmap for candidate %s: %s", payload.candidate_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Roadmap refresh failed: {exc!s}",
        ) from exc
