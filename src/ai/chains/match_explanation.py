from typing import Optional, Any
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from src.core.llm import get_llm
from src.middleware.llm_middleware import truncate_to_token_limit
from src.schemas.match import SkillGapAnalysisResponse
from src.ai.prompts.match_reasoning import (
    SKILL_GAP_ANALYSIS_SYSTEM_PROMPT,
    SKILL_GAP_ANALYSIS_USER_TEMPLATE,
)

class MatchExplanationChain:
    """
    LangChain-powered AI Technical Recruiter chain for automated Skill Gap Analysis.
    Evaluates candidate credentials against job requirements and yields a strictly-typed
    SkillGapAnalysisResponse.
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self._custom_llm = llm
        self.model_name = model_name
        self.temperature = temperature
        self.base_url = base_url
        self.api_key = api_key

    def get_active_llm(self) -> BaseChatModel:
        """Resolves the active LLM based on explicit arguments, context headers, or app settings."""
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
        return self.get_active_llm()

    async def analyze_skill_gap(
        self,
        job_id: str,
        candidate_id: str,
        job_requirements_str: str,
        candidate_profile_str: str,
    ) -> SkillGapAnalysisResponse:
        # Safeguard token budgets for prompt inputs
        safe_job_reqs = truncate_to_token_limit(job_requirements_str, max_tokens=2000)
        safe_candidate_prof = truncate_to_token_limit(candidate_profile_str, max_tokens=3000)

        prompt = ChatPromptTemplate.from_messages([
            ("system", SKILL_GAP_ANALYSIS_SYSTEM_PROMPT),
            ("user", SKILL_GAP_ANALYSIS_USER_TEMPLATE)
        ])

        messages = prompt.format_messages(
            job_id=job_id,
            candidate_id=candidate_id,
            job_requirements=safe_job_reqs,
            candidate_profile=safe_candidate_prof,
        )

        active_llm = self.get_active_llm()
        structured_evaluator = active_llm.with_structured_output(SkillGapAnalysisResponse)
        res: SkillGapAnalysisResponse = await structured_evaluator.ainvoke(messages)

        # Enforce consistency of root IDs
        res.job_id = job_id
        res.candidate_id = candidate_id
        return res
