import asyncio
import logging
from typing import Dict, Any
from celery import Celery
from src.core.config import settings
from src.db.base import SessionLocal
from src.db.repositories.match_repository import MatchRepository
from src.db.repositories.interview_repository import InterviewRepository
from src.schemas.match import SkillGapAnalysisRequest, SkillGapAnalysisResponse
from src.schemas.interview import QuestionGenerationRequest, AnswerSubmission
from src.services.matching_service import matching_service
from src.services.interview_service import interview_service
from src.services.review_queue_service import review_queue_service

logger = logging.getLogger(__name__)

# Initialize Celery app
broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
result_backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

celery_app = Celery(
    "skillmatch_workers",
    broker=broker_url,
    backend=result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=2.0,
    broker_transport_options={
        "visibility_timeout": 3600,
        "socket_timeout": getattr(settings, "REDIS_SOCKET_TIMEOUT", 2.0),
        "socket_connect_timeout": getattr(settings, "REDIS_CONNECT_TIMEOUT", 2.0),
    },
    result_backend_transport_options={
        "socket_timeout": getattr(settings, "REDIS_SOCKET_TIMEOUT", 2.0),
        "socket_connect_timeout": getattr(settings, "REDIS_CONNECT_TIMEOUT", 2.0),
    },
)

def run_async(coro):
    """Executes an async coroutine inside a synchronous Celery task worker."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

@celery_app.task(name="tasks.async_analyze_skill_gap", bind=True, max_retries=2)
def async_analyze_skill_gap(
    self,
    payload_dict: Dict[str, Any],
    auto_persist: bool = True,
    auto_enqueue_review: bool = True
) -> Dict[str, Any]:
    """
    Background worker task for automated skill gap analysis.
    Evaluates candidate, persists result to repository, and routes to review queue if flagged.
    """
    try:
        logger.info(f"Worker started async_analyze_skill_gap for job={payload_dict.get('job_id')}")
        req = SkillGapAnalysisRequest(**payload_dict)
        analysis_result: SkillGapAnalysisResponse = run_async(matching_service.analyze_skill_gap(req))

        # Persist to database if requested
        if auto_persist:
            db = SessionLocal()
            try:
                repo = MatchRepository(db)
                repo.save_match_result(analysis_result)

                # Route to human review queue if borderline or flagged
                if auto_enqueue_review:
                    review_queue_service.enqueue_match_if_needed(analysis_result, db=db)
            finally:
                db.close()

        logger.info(f"Worker completed async_analyze_skill_gap successfully.")
        return analysis_result.model_dump()
    except Exception as exc:
        logger.error(f"Error in async_analyze_skill_gap: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=5)

@celery_app.task(name="tasks.async_generate_interview_questions", bind=True, max_retries=2)
def async_generate_interview_questions(
    self,
    payload_dict: Dict[str, Any],
    auto_persist: bool = True
) -> Dict[str, Any]:
    """Background worker task for generating interview questions."""
    try:
        req = QuestionGenerationRequest(**payload_dict)
        question_set = run_async(interview_service.create_prep_session(req))

        if auto_persist:
            db = SessionLocal()
            try:
                repo = InterviewRepository(db)
                repo.save_session(question_set, candidate_id=req.candidate_id)
            finally:
                db.close()

        return question_set.model_dump()
    except Exception as exc:
        logger.error(f"Error in async_generate_interview_questions: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=5)

@celery_app.task(name="tasks.async_evaluate_interview_answer", bind=True, max_retries=2)
def async_evaluate_interview_answer(
    self,
    payload_dict: Dict[str, Any],
    session_id: str = None,
    auto_persist: bool = True
) -> Dict[str, Any]:
    """Background worker task for evaluating interview responses and security auditing."""
    try:
        sub = AnswerSubmission(**payload_dict)
        evaluation = run_async(interview_service.evaluate_submission(sub))

        if auto_persist:
            db = SessionLocal()
            try:
                repo = InterviewRepository(db)
                repo.save_answer_evaluation(evaluation, session_id=session_id)
            finally:
                db.close()

        return evaluation.model_dump()
    except Exception as exc:
        logger.error(f"Error in async_evaluate_interview_answer: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=5)
