import uuid
from typing import Optional
from src.ai.chains.interview_coach import InterviewCoachChains
from src.schemas.interview import (
    QuestionGenerationRequest,
    QuestionSetResponse,
    AnswerSubmission,
    AnswerEvaluationResponse
)

class InterviewService:
    def __init__(self, chains: Optional[InterviewCoachChains] = None):
        self.chains = chains or InterviewCoachChains()

    async def create_prep_session(self, req: QuestionGenerationRequest) -> QuestionSetResponse:
        skills_to_target = req.focus_skills if req.focus_skills else []

        # Resolve job summary dynamically from request or role context
        if req.job_summary:
            job_summary = req.job_summary
        else:
            skills_text = f" with focus in {', '.join(skills_to_target)}" if skills_to_target else ""
            job_summary = (
                f"Candidate preparation for {req.target_role}{skills_text}. "
                f"Evaluation of core competencies, architecture, security, and practical problem solving."
            )

        question_set = await self.chains.generate_questions(
            target_role=req.target_role,
            focus_skills=skills_to_target,
            job_summary=job_summary,
            job_id=req.job_id,
            include_essay=req.include_essay
        )

        for q in question_set.questions:
            if not q.question_id:
                q.question_id = f"q_{uuid.uuid4().hex[:6]}"

        return question_set

    async def evaluate_submission(self, sub: AnswerSubmission) -> AnswerEvaluationResponse:
        return await self.chains.evaluate_answer(
            question_id=sub.question_id,
            question_text=sub.question_text,
            question_type=sub.question_type or "technical",
            skill_id=sub.skill_id,
            user_answer=sub.user_answer
        )

interview_service = InterviewService()
