from __future__ import annotations
"""SQLAlchemy ORM models for SkillMatch AI Services persistence."""

from src.db.models.interview import InterviewAnswerEvaluationModel, InterviewSessionModel
from src.db.models.job_requirement import JobRequirementModel
from src.db.models.match import MatchRecordModel
from src.db.models.review_queue import ReviewQueueModel
from src.db.models.roadmap import RoadmapModel
from src.db.models.skill_resource import SkillResourceModel
from src.db.models.candidate import CandidateModel
from src.db.models.interaction import CandidateInteractionModel
from src.models.mentor_conversation import MentorConversation
from src.models.mentor_message import MentorMessage

__all__ = [
    "JobRequirementModel",
    "MatchRecordModel",
    "InterviewSessionModel",
    "InterviewAnswerEvaluationModel",
    "ReviewQueueModel",
    "RoadmapModel",
    "SkillResourceModel",
    "CandidateModel",
    "CandidateInteractionModel",
    "MentorConversation",
    "MentorMessage",
]
