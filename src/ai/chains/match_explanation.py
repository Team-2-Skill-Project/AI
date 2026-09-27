from __future__ import annotations
from typing import Optional, Any, cast
from langchain_core.language_models import BaseChatModel

from langchain_core.prompts import ChatPromptTemplate
from src.core.llm import get_llm, truncate_to_token_limit
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
    ):
        self._custom_llm = llm

    def get_active_llm(self) -> BaseChatModel:
        """Resolves the active LLM from injected instance or canonical get_llm()."""
        if self._custom_llm is not None:
            return self._custom_llm
        return get_llm()

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
        raw_res = await structured_evaluator.ainvoke(messages)
        if isinstance(raw_res, dict):
            res: SkillGapAnalysisResponse = SkillGapAnalysisResponse.model_validate(raw_res)
        else:
            res = cast(SkillGapAnalysisResponse, raw_res)

        # Enforce consistency of root IDs
        res.job_id = job_id
        res.candidate_id = candidate_id
        return res

