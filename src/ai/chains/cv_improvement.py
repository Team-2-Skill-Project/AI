"""Centralized-LLM chain for untrusted CV improvement drafts."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.ai.prompts.cv_improvement import (
    CV_IMPROVEMENT_REPAIR_SYSTEM_PROMPT,
    CV_IMPROVEMENT_REPAIR_USER_TEMPLATE,
    CV_IMPROVEMENT_SYSTEM_PROMPT,
    CV_IMPROVEMENT_USER_TEMPLATE,
)
from src.core.llm import get_llm, parse_json_response, truncate_to_token_limit
from src.models.cv_improvement import LLMImprovementDraft


class CVImprovementChain:
    """Produce an untrusted structured draft through the one canonical LLM path."""

    def __init__(self, llm: Any | None = None) -> None:
        self._custom_llm = llm

    def get_active_llm(self) -> BaseChatModel:
        return self._custom_llm if self._custom_llm is not None else get_llm()

    async def generate_draft(
        self,
        candidate: Any,
        target_job: Any,
        gap_result: Any,
        evidence_catalog: list[Any] | None = None,
        target_reference_catalog: list[Any] | None = None,
        opportunities: list[Any] | None = None,
    ) -> LLMImprovementDraft:
        """Generate a draft that can cite only supplied opaque catalog IDs."""
        del candidate, target_job, gap_result
        prompt = ChatPromptTemplate.from_messages(
            [("system", CV_IMPROVEMENT_SYSTEM_PROMPT), ("user", CV_IMPROVEMENT_USER_TEMPLATE)]
        )
        messages = prompt.format_messages(
            evidence_catalog_json=truncate_to_token_limit(
                json.dumps([item.model_dump() for item in evidence_catalog or []], ensure_ascii=False), max_tokens=6_000
            ),
            target_reference_catalog_json=truncate_to_token_limit(
                json.dumps([item.model_dump() for item in target_reference_catalog or []], ensure_ascii=False),
                max_tokens=2_500,
            ),
            opportunities_json=json.dumps([item.model_dump() for item in opportunities or []], ensure_ascii=False),
        )

        active_llm = self.get_active_llm()
        if hasattr(active_llm, "with_structured_output"):
            response = await active_llm.with_structured_output(LLMImprovementDraft).ainvoke(messages)
            if isinstance(response, LLMImprovementDraft):
                return response
            return LLMImprovementDraft.model_validate(response)

        response = await active_llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else response
        parsed = parse_json_response(str(content))
        if not isinstance(parsed, dict):
            raise ValueError("LLM improvement draft must be a JSON object")
        return LLMImprovementDraft.model_validate(parsed)

    async def repair_draft(
        self,
        draft: LLMImprovementDraft,
        validation_errors: list[dict[str, Any]],
        evidence_catalog: list[Any],
        target_reference_catalog: list[Any],
        opportunities: list[Any],
    ) -> LLMImprovementDraft:
        """Perform one constrained format-only repair of a previous draft."""
        prompt = ChatPromptTemplate.from_messages(
            [("system", CV_IMPROVEMENT_REPAIR_SYSTEM_PROMPT), ("user", CV_IMPROVEMENT_REPAIR_USER_TEMPLATE)]
        )
        messages = prompt.format_messages(
            evidence_catalog_json=truncate_to_token_limit(
                json.dumps([item.model_dump() for item in evidence_catalog], ensure_ascii=False), max_tokens=6_000
            ),
            target_reference_catalog_json=truncate_to_token_limit(
                json.dumps([item.model_dump() for item in target_reference_catalog], ensure_ascii=False), max_tokens=2_500
            ),
            opportunities_json=json.dumps([item.model_dump() for item in opportunities], ensure_ascii=False),
            draft_json=json.dumps(draft.model_dump(), ensure_ascii=False),
            validation_errors_json=json.dumps(validation_errors, ensure_ascii=False),
        )
        active_llm = self.get_active_llm()
        if hasattr(active_llm, "with_structured_output"):
            response = await active_llm.with_structured_output(LLMImprovementDraft).ainvoke(messages)
            if isinstance(response, LLMImprovementDraft):
                return response
            return LLMImprovementDraft.model_validate(response)
        response = await active_llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else response
        parsed = parse_json_response(str(content))
        if not isinstance(parsed, dict):
            raise ValueError("LLM improvement repair must be a JSON object")
        return LLMImprovementDraft.model_validate(parsed)
