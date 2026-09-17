from __future__ import annotations
"""Factory for instantiating role-family-specific Roadmap Generation Chains."""

from typing import Any, Optional
from src.ai.chains.roadmap_chain import RoadmapGenerationChain


class RoadmapChainFactory:
    """Factory for selecting and instantiating structured roadmap chains per role family."""

    @staticmethod
    def for_role_family(
        role_family: str,
        llm: Optional[Any] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> RoadmapGenerationChain:
        normalized_family = (role_family or "Engineering").strip().lower()

        if "data" in normalized_family:
            family_key = "Data & Analytics"
        elif "front" in normalized_family or "ui" in normalized_family or "web" in normalized_family:
            family_key = "Frontend Engineering"
        elif "back" in normalized_family or "engine" in normalized_family or "dev" in normalized_family:
            family_key = "Backend Engineering"
        else:
            family_key = "General Technical"

        return RoadmapGenerationChain(
            llm=llm,
            role_family=family_key,
            model_name=model_name,
            temperature=temperature,
        )
