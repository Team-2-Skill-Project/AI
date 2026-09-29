from __future__ import annotations
import copy
import json
import logging
import uuid
from typing import Optional, List, Dict, Any, Union
from sqlalchemy.orm import Session

# pyrefly: ignore [missing-import]
from src.ai.chains.interview_coach import InterviewCoachChains
from src.ai.chains.interview_practice import PracticeInterviewChains
# pyrefly: ignore [missing-import]
from src.schemas.interview import (
    QuestionGenerationRequest,
    QuestionSetResponse,
    AnswerSubmission,
    AnswerEvaluationResponse,
    PracticeQuestionGenerationRequest,
    PracticeSessionQuestionsResponse,
    PracticeSubmissionRequest,
    PracticeEvaluationResponse,
    PracticeSessionDetailResponse,
    MCQQuestion,
    EssayQuestion,
    MCQEvaluationItem,
    EssayEvaluationItem,
    OverallScore,
)
from src.db.models.interview import InterviewSessionModel

logger = logging.getLogger(__name__)

DIFFICULTY_POINTS: Dict[str, int] = {
    "easy": 1,
    "medium": 2,
    "hard": 3,
}


def sanitize_question_for_client(question: Union[MCQQuestion, EssayQuestion, Dict[str, Any]]) -> Dict[str, Any]:
    """Sanitizes question data by omitting correct answers and rubrics before sending to client."""
    if isinstance(question, dict):
        q_dict = copy.deepcopy(question)
    elif hasattr(question, "model_dump"):
        q_dict = question.model_dump()
    else:
        q_dict = dict(question)

    q_type = q_dict.get("type", "mcq")
    if q_type == "mcq":
        q_dict.pop("correct_option_id", None)
        q_dict.pop("explanation", None)
    elif q_type == "essay":
        q_dict.pop("reference_answer", None)
        q_dict.pop("grading_criteria", None)

    return q_dict


class InterviewService:
    def __init__(
        self,
        chains: Optional[InterviewCoachChains] = None,
        practice_chains: Optional[PracticeInterviewChains] = None,
    ):
        self.chains = chains or InterviewCoachChains()
        self.practice_chains = practice_chains or PracticeInterviewChains()

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

    # ----------------------------------------------------------------------
    # Practice Coach (MCQ + Essay + Structured Scoring) (§1-§8 Requirements)
    # ----------------------------------------------------------------------

    async def generate_practice_session(
        self,
        req: PracticeQuestionGenerationRequest,
        db: Optional[Session] = None,
        mask_answers: bool = True,
    ) -> Dict[str, Any]:
        """
        Generates practice questions driven by track and skill_gaps,
        persists the session in the database, and returns the session questions
        (sanitizing true answers/rubrics for client consumption if mask_answers is True).
        """
        session_id = f"sess_{uuid.uuid4().hex[:8]}"

        generated_questions = await self.practice_chains.generate_practice_questions(
            track=req.track,
            skill_gaps=req.skill_gaps,
            job_id=req.job_id,
            total_questions=req.total_questions or 4,
            include_essay=req.include_essay,
        )

        # Full questions dict (with true answers) for storage
        full_questions_dict = [
            q.model_dump() if hasattr(q, "model_dump") else dict(q)
            for q in generated_questions
        ]

        if db is not None:
            try:
                db_session = InterviewSessionModel(
                    id=session_id,
                    job_id=req.job_id,
                    candidate_id=req.user_id,
                    track=req.track,
                    target_role=req.track,
                    skill_gaps_json=json.dumps(req.skill_gaps),
                    questions_json=json.dumps(full_questions_dict),
                )
                db.add(db_session)
                db.commit()
            except Exception as exc:
                logger.error("Failed to persist practice session %s: %s", session_id, exc)
                if db:
                    db.rollback()

        client_questions = (
            [sanitize_question_for_client(q) for q in full_questions_dict]
            if mask_answers
            else full_questions_dict
        )

        return {
            "session_id": session_id,
            "user_id": req.user_id,
            "job_id": req.job_id,
            "track": req.track,
            "skill_gaps": req.skill_gaps,
            "questions": client_questions,
        }

    def score_mcq_item(
        self,
        question_id: str,
        correct_option_id: Optional[str],
        submitted_option_id: Optional[str],
        difficulty: str = "medium",
        explanation: Optional[str] = None,
    ) -> MCQEvaluationItem:
        """Deterministically grades an MCQ question without any LLM call."""
        points_possible = DIFFICULTY_POINTS.get((difficulty or "medium").lower(), 1)

        sub_clean = (submitted_option_id or "").strip().lower()
        corr_clean = (correct_option_id or "").strip().lower()

        is_correct = bool(sub_clean and corr_clean and sub_clean == corr_clean)
        points_earned = points_possible if is_correct else 0

        exp_suffix = f" {explanation}" if explanation else ""

        if not submitted_option_id or not submitted_option_id.strip():
            feedback = f"No answer was submitted. The correct option is '{correct_option_id}'.{exp_suffix}"
        elif is_correct:
            feedback = f"Correct! Option '{submitted_option_id}' is the right answer.{exp_suffix}"
        else:
            feedback = f"Incorrect. You selected option '{submitted_option_id}', but the correct answer is '{correct_option_id}'.{exp_suffix}"

        return MCQEvaluationItem(
            question_id=question_id,
            type="mcq",
            is_correct=is_correct,
            points_earned=points_earned,
            points_possible=points_possible,
            feedback=feedback,
        )

    async def evaluate_practice_submission(
        self,
        sub: PracticeSubmissionRequest,
        db: Optional[Session] = None,
    ) -> PracticeEvaluationResponse:
        """
        Evaluates a candidate's practice submission:
        - Deterministic scoring for MCQ questions.
        - Structured LLM grading for Essay questions with rubric & timeout fallback.
        - Calculates raw points, max points, percentage, and summary feedback.
        - Persists answers and evaluation in DB.
        """
        # Retrieve session context if stored in DB to hydrate missing question metadata
        stored_session: Optional[InterviewSessionModel] = None
        stored_questions_by_id: Dict[str, Dict[str, Any]] = {}
        track: str = "General"
        if db is not None and sub.session_id:
            try:
                stored_session = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == sub.session_id).first()
                if stored_session:
                    track = str(stored_session.track or stored_session.target_role or "General")
                    if stored_session.questions_json:
                        for q in json.loads(str(stored_session.questions_json)):
                            qid = q.get("id") or q.get("question_id")
                            if qid:
                                stored_questions_by_id[qid] = q
            except Exception as exc:
                logger.warning("Could not load session %s from DB: %s", sub.session_id, exc)

        per_question_results: List[Union[MCQEvaluationItem, EssayEvaluationItem]] = []

        for ans in sub.answers:
            stored_q = stored_questions_by_id.get(ans.question_id, {})
            q_type = ans.type.lower() if ans.type else stored_q.get("type", "mcq").lower()

            if q_type == "mcq":
                correct_opt = ans.correct_option_id or stored_q.get("correct_option_id")
                difficulty = stored_q.get("difficulty", "medium")
                explanation = stored_q.get("explanation")

                eval_item = self.score_mcq_item(
                    question_id=ans.question_id,
                    correct_option_id=correct_opt,
                    submitted_option_id=ans.submitted_option_id,
                    difficulty=difficulty,
                    explanation=explanation,
                )
                per_question_results.append(eval_item)

            elif q_type == "essay":
                ref_ans = ans.reference_answer or stored_q.get("reference_answer", "")
                criteria = ans.grading_criteria or stored_q.get("grading_criteria", [])
                prompt = stored_q.get("prompt") or f"Essay question {ans.question_id}"
                skill_tag = stored_q.get("skill_tag", "General")

                eval_item = await self.practice_chains.grade_essay(
                    question_id=ans.question_id,
                    prompt=prompt,
                    skill_tag=skill_tag,
                    reference_answer=ref_ans,
                    grading_criteria=criteria,
                    submitted_answer=ans.submitted_answer or "",
                )
                per_question_results.append(eval_item)

        # Calculate overall score
        raw_points = 0.0
        max_points = 0.0

        for res in per_question_results:
            if isinstance(res, MCQEvaluationItem):
                raw_points += res.points_earned
                max_points += res.points_possible
            elif isinstance(res, EssayEvaluationItem):
                if res.score is not None:
                    raw_points += res.score
                max_points += res.points_possible

        percentage = round((raw_points / max_points) * 100.0, 1) if max_points > 0 else 0.0

        overall_score = OverallScore(
            raw_points=round(raw_points, 1),
            max_points=round(max_points, 1),
            percentage=percentage,
        )

        summary_feedback = await self.practice_chains.generate_summary_feedback(
            track=track,
            percentage=percentage,
            raw_points=raw_points,
            max_points=max_points,
            per_question_results=per_question_results,
        )

        eval_response = PracticeEvaluationResponse(
            session_id=sub.session_id,
            per_question=per_question_results,
            overall_score=overall_score,
            summary_feedback=summary_feedback,
        )

        # Persist submission and evaluation if DB available
        if db is not None:
            try:
                answers_data = [
                    a.model_dump() if hasattr(a, "model_dump") else dict(a)
                    for a in sub.answers
                ]
                eval_data = eval_response.model_dump() if hasattr(eval_response, "model_dump") else dict(eval_response)

                if stored_session:
                    setattr(stored_session, "answers_json", json.dumps(answers_data))
                    setattr(stored_session, "evaluation_json", json.dumps(eval_data))
                    db.commit()
                else:
                    # Create session entry if not pre-created
                    new_session = InterviewSessionModel(
                        id=sub.session_id,
                        job_id=sub.job_id or "job_unknown",
                        candidate_id=sub.user_id or "user_unknown",
                        track=track,
                        target_role=track,
                        questions_json=json.dumps([]),
                        answers_json=json.dumps(answers_data),
                        evaluation_json=json.dumps(eval_data),
                    )
                    db.add(new_session)
                    db.commit()
            except Exception as exc:
                logger.error("Failed to persist practice evaluation for session %s: %s", sub.session_id, exc)
                if db:
                    db.rollback()

        return eval_response

    def get_practice_session(
        self,
        session_id: str,
        db: Session,
    ) -> Optional[PracticeSessionDetailResponse]:
        """Retrieves past practice session details, questions, submitted answers, and evaluation result."""
        session = db.query(InterviewSessionModel).filter(InterviewSessionModel.id == session_id).first()
        if not session:
            return None

        data = session.to_dict()
        return PracticeSessionDetailResponse(
            session_id=data["session_id"],
            user_id=data["user_id"],
            job_id=data["job_id"],
            track=data.get("track"),
            skill_gaps=data.get("skill_gaps", []),
            questions=data.get("questions", []),
            answers=data.get("answers"),
            evaluation=data.get("evaluation"),
            created_at=data.get("created_at"),
        )


interview_service = InterviewService()

