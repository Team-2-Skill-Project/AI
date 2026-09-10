from typing import Optional, List, Any
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate
from src.core.llm import get_llm
from src.middleware.llm_middleware import truncate_to_token_limit
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
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initializes the interview coach chains.
        If an explicit LLM is provided, it is retained.
        Otherwise, delegates dynamically to get_llm() per request, allowing
        dynamic header overrides (base_url, model_name, api_token) to take effect.
        """
        self._custom_llm = llm
        self.model_name = model_name
        self.temperature = temperature
        self.base_url = base_url
        self.api_key = api_key

    def get_active_llm(self) -> BaseChatModel:
        """Resolves the active LLM based on explicit args, request context, or .env defaults."""
        if self._custom_llm is not None:
            return self._custom_llm
        return get_llm(
            model=self.model_name,
            temperature=self.temperature,
            base_url=self.base_url,
            api_key=self.api_key,
        )

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
        res: QuestionSetResponse = await question_generator.ainvoke(formatted)
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
        res: AnswerEvaluationResponse = await evaluator.ainvoke(formatted)
        res.question_id = question_id
        return res
