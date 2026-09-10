import logging
from typing import Dict, Any, Optional
from src.core.redis import is_redis_available
from src.workers.tasks import (
    celery_app,
    async_analyze_skill_gap,
    async_generate_interview_questions,
    async_evaluate_interview_answer,
)

logger = logging.getLogger(__name__)

class TaskDispatcher:
    """
    Unified task dispatcher that queues jobs to Celery workers backed by Redis
    when available, or falls back to immediate synchronous execution for local
    testing and lightweight environments.
    """

    @staticmethod
    def dispatch_skill_gap_analysis(
        payload: Dict[str, Any],
        use_celery: bool = True
    ) -> Dict[str, Any]:
        """Dispatches skill gap analysis task."""
        if use_celery and is_redis_available():
            try:
                task = async_analyze_skill_gap.delay(payload)
                return {"task_id": str(task.id), "status": "queued", "mode": "celery"}
            except Exception as e:
                logger.warning(f"Failed to queue to Celery broker ({e}); falling back to synchronous execution.")

        # Synchronous execution fallback
        result = async_analyze_skill_gap(payload)
        return {"task_id": "direct_sync", "status": "completed", "result": result, "mode": "sync"}

    @staticmethod
    def dispatch_interview_generation(
        payload: Dict[str, Any],
        use_celery: bool = True
    ) -> Dict[str, Any]:
        """Dispatches interview question generation task."""
        if use_celery and is_redis_available():
            try:
                task = async_generate_interview_questions.delay(payload)
                return {"task_id": str(task.id), "status": "queued", "mode": "celery"}
            except Exception as e:
                logger.warning(f"Failed to queue to Celery broker ({e}); falling back to synchronous execution.")

        result = async_generate_interview_questions(payload)
        return {"task_id": "direct_sync", "status": "completed", "result": result, "mode": "sync"}

    @staticmethod
    def dispatch_answer_evaluation(
        payload: Dict[str, Any],
        session_id: Optional[str] = None,
        use_celery: bool = True
    ) -> Dict[str, Any]:
        """Dispatches answer evaluation task."""
        if use_celery and is_redis_available():
            try:
                task = async_evaluate_interview_answer.delay(payload, session_id=session_id)
                return {"task_id": str(task.id), "status": "queued", "mode": "celery"}
            except Exception as e:
                logger.warning(f"Failed to queue to Celery broker ({e}); falling back to synchronous execution.")

        result = async_evaluate_interview_answer(payload, session_id=session_id)
        return {"task_id": "direct_sync", "status": "completed", "result": result, "mode": "sync"}

task_dispatcher = TaskDispatcher()
