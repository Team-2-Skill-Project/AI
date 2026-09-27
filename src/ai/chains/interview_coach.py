from __future__ import annotations
from typing import Optional, List, Any, cast

from langchain_core.language_models import BaseChatModel

from langchain_core.prompts import PromptTemplate
from src.core.llm import get_llm, truncate_to_token_limit
from src.schemas.interview import QuestionSetResponse, AnswerEvaluationResponse

QUESTION_GEN_PROMPT = """
You are an expert AI Technical Interviewer.

Target Role: {target_role}
Focus Skills/Gaps: {focus_skills}
Job Requirements Summary: {job_summary}
Include Essay Questions: {include_essay}

Generate 3-5 realistic interview questions (technical, behavioral, system_design, or essay).
For essay and system_design questions, include explicit `security_focus_areas` (e.g., OWASP Top 10, input sanitization, RBAC, data encryption) and key points to cover.
"""

EVALUATION_PROMPT = """
You are an expert Technical Interview Coach and Security Auditor. Evaluate the candidate's response.

Question: {question_text}
Question Type: {question_type}
Target Skill: {skill_id}
Candidate Answer: {user_answer}

Perform a dual-layer evaluation:
1. Overall content quality, clarity, and depth (Overall Score 1-10, Strengths, Improvements, Ideal Answer Outline).
2. Security Assessment: Analyze the answer for security vulnerabilities, missing controls, or architectural risks. Assign a security score (1-10) and detail mitigations.
"""

class InterviewCoachChains:
    def __init__(
        self,
        llm: Optional[Any] = None,
    ):
        """
        Initializes the interview coach chains.
        If an explicit LLM is provided, it is retained.
        Otherwise, delegates to canonical get_llm().
        """
        self._custom_llm = llm

    def get_active_llm(self) -> BaseChatModel:
        """Resolves the active LLM from injected instance or canonical get_llm()."""
        if self._custom_llm is not None:
            return self._custom_llm
        return get_llm()

    @property
    def llm(self) -> BaseChatModel:
        """Property for accessing the currently resolved LLM instance."""
        return self.get_active_llm()

    async def generate_questions(
        self,
        target_role: str,
        focus_skills: List[str],
        job_summary: str,
        job_id: str,
        include_essay: bool,
    ) -> QuestionSetResponse:
        # Apply token safety guard to job summary
        safe_summary = truncate_to_token_limit(job_summary, max_tokens=1500)

        prompt = PromptTemplate(
            template=QUESTION_GEN_PROMPT,
            input_variables=["target_role", "focus_skills", "job_summary", "include_essay"],
        )
        formatted = prompt.format(
            target_role=target_role,
            focus_skills=", ".join(focus_skills) if focus_skills else "General technical skills",
            job_summary=safe_summary,
            include_essay=str(include_essay),
        )

        active_llm = self.get_active_llm()
        question_generator = active_llm.with_structured_output(QuestionSetResponse)
        raw_res = await question_generator.ainvoke(formatted)
        if isinstance(raw_res, dict):
            res: QuestionSetResponse = QuestionSetResponse.model_validate(raw_res)
        else:
            res = cast(QuestionSetResponse, raw_res)
        res.job_id = job_id
        return res

    async def evaluate_answer(
        self,
        question_id: str,
        question_text: str,
        question_type: str,
        skill_id: Optional[str],
        user_answer: str,
    ) -> AnswerEvaluationResponse:
        # Apply token safety guard to candidate answer
        safe_user_answer = truncate_to_token_limit(user_answer, max_tokens=2000)

        prompt = PromptTemplate(
            template=EVALUATION_PROMPT,
            input_variables=["question_text", "question_type", "skill_id", "user_answer"],
        )
        formatted = prompt.format(
            question_text=question_text,
            question_type=question_type or "technical",
            skill_id=skill_id or "General",
            user_answer=safe_user_answer,
        )

        active_llm = self.get_active_llm()
        evaluator = active_llm.with_structured_output(AnswerEvaluationResponse)
        raw_eval = await evaluator.ainvoke(formatted)
        if isinstance(raw_eval, dict):
            res: AnswerEvaluationResponse = AnswerEvaluationResponse.model_validate(raw_eval)
        else:
            res = cast(AnswerEvaluationResponse, raw_eval)
        res.question_id = question_id
        return res

