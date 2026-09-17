from __future__ import annotations
"""
LLM-backed extractor for the Job Description Understanding pipeline.

Mirrors the pattern of src/cv_extractor/llm_extractor.py:
  - Uses the canonical get_llm() path (no provider instantiation here).
  - Validates raw LLM output against JobRequirementProfile via Pydantic.
  - Raises ValueError with a clear diagnostic on parse/validation failure.
"""

import logging
from typing import Any

from pydantic import ValidationError

from src.core.config import settings
from src.core.llm import get_llm, parse_json_response

from .models import JobRequirementProfile, RawSkillItem
from .prompt_builder import build_prompt

logger = logging.getLogger(__name__)


class JobLLMExtractor:
    """
    Extracts a structured JobRequirementProfile from raw job description text.

    Uses the canonical LLM to call the configured provider, then
    validates the response against the Pydantic schema.
    """

    def __init__(self, llm=None):
        self.llm = llm

    def _llm_available(self) -> bool:
        if self.llm is not None and hasattr(self.llm, "is_available"):
            return bool(self.llm.is_available())
        if self.llm is not None:
            return True
        llm_settings = settings.get_llm_settings()
        return bool(llm_settings.api_key) or bool(llm_settings.base_url)

    def _generate_json(self, prompt: str, system_prompt: str):
        if self.llm is not None and hasattr(self.llm, "generate_json"):
            return self.llm.generate_json(prompt=prompt, system_prompt=system_prompt)
        if self.llm is None:
            self.llm = get_llm()
        response = self.llm.invoke([("system", system_prompt), ("user", prompt)])
        return parse_json_response(str(getattr(response, "content", response)))

    def extract(self, job_description: str) -> dict[str, Any]:
        """
        Call the LLM with the structured zero-fabrication prompt and return the
        raw validated dict (pre-normalization).

        Raises:
            ValueError: if the LLM is unavailable, returns invalid JSON,
                        or fails Pydantic schema validation.
        """
        if not self._llm_available():
            raise ValueError(
                "LLM service is not available. "
                "Configure a valid LLM provider API key (GROQ_API_KEY, GEMINI_API_KEY, etc.)."
            )

        system_prompt, user_prompt = build_prompt(job_description)

        try:
            raw_result = self._generate_json(
                prompt=user_prompt,
                system_prompt=system_prompt,
            )
        except Exception as e:
            logger.error("LLM call failed during job description extraction: %s", e, exc_info=True)
            raise ValueError(f"LLM extraction failed: {e}") from e

        if not isinstance(raw_result, dict):
            raise ValueError(
                f"LLM returned unexpected type {type(raw_result).__name__}; expected a JSON object."
            )

        # Validate the raw dict partially — skill lists are validated later after normalization.
        # We do a lenient pass here: unknown fields are ignored, missing optionals get defaults.
        try:
            validated = _validate_raw(raw_result)
        except ValidationError as ve:
            logger.error("Schema validation failed for LLM job extraction output: %s", ve)
            raise ValueError(f"LLM output failed schema validation: {ve}") from ve

        logger.info(
            "Job description extraction succeeded — role_family=%s, seniority=%s, "
            "required_skills=%d, preferred_skills=%d",
            validated.get("role_family"),
            validated.get("seniority"),
            len(validated.get("required_skills", [])),
            len(validated.get("preferred_skills", [])),
        )
        return validated


def _validate_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Performs a partial Pydantic validation of the LLM output dict.

    Skills are kept as raw dicts (RawSkillItem) here; full NormalizedSkill
    objects are built by the skill_normalizer after taxonomy lookup.
    """
    # Validate scalar fields + skill name/importance/level through RawSkillItem
    raw_required = [_coerce_skill(s) for s in raw.get("required_skills", []) if isinstance(s, dict)]
    raw_preferred = [_coerce_skill(s) for s in raw.get("preferred_skills", []) if isinstance(s, dict)]

    responsibilities = [str(r) for r in raw.get("responsibilities", []) if r]
    constraints = [str(c) for c in raw.get("constraints", []) if c]

    min_exp = _safe_int(raw.get("min_years_experience"))
    max_exp = _safe_int(raw.get("max_years_experience"))

    return {
        "role_family": _safe_str(raw.get("role_family")),
        "seniority": _safe_str(raw.get("seniority")),
        "canonical_role": _safe_str(raw.get("canonical_role")),
        "required_skills": raw_required,
        "preferred_skills": raw_preferred,
        "responsibilities": responsibilities,
        "min_years_experience": min_exp,
        "max_years_experience": max_exp,
        "constraints": constraints,
    }


def _coerce_skill(raw_skill: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw LLM skill dict into a validated RawSkillItem dict."""
    item = RawSkillItem.model_validate({
        "name": str(raw_skill.get("name", "")).strip(),
        "importance": raw_skill.get("importance", "important"),
        "required_level": raw_skill.get("required_level"),
    })
    return item.model_dump()


def _safe_str(value: Any) -> str | None:
    """Return stripped string or None for null/empty."""
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def _safe_int(value: Any) -> int | None:
    """Return integer or None for null/non-numeric values."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
