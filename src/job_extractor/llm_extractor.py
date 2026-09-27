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

    def _get_active_llm(self):
        if self.llm is not None:
            if hasattr(self.llm, "is_available") and not self.llm.is_available():
                raise ValueError(
                    "LLM service is not configured. Set LLM_PROVIDER, LLM_MODEL, and LLM_API_KEY."
                )
            return self.llm
        try:
            return get_llm()
        except Exception as exc:
            raise ValueError(
                f"LLM service is not configured. Set LLM_PROVIDER, LLM_MODEL, and LLM_API_KEY. ({exc})"
            ) from exc

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        """Extract textual content in original order from LLM response or content blocks."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    if block.get("type") == "text" and "text" in block:
                        parts.append(str(block["text"]))
                    elif "text" in block:
                        parts.append(str(block["text"]))
                elif hasattr(block, "text"):
                    parts.append(str(getattr(block, "text")))
                elif hasattr(block, "content"):
                    parts.append(str(getattr(block, "content")))
            return "".join(parts)
        return str(content) if content is not None else ""

    def _generate_json(self, prompt: str, system_prompt: str):
        active_llm = self._get_active_llm()
        if hasattr(active_llm, "generate_json"):
            result = active_llm.generate_json(prompt=prompt, system_prompt=system_prompt)
            if isinstance(result, str):
                return parse_json_response(result)
            return result
        response = active_llm.invoke([("system", system_prompt), ("user", prompt)])
        raw_content = getattr(response, "content", response)
        text = self._extract_text_content(raw_content)
        return parse_json_response(text)

    def extract(self, job_description: str) -> dict[str, Any]:
        """
        Call the LLM with the structured zero-fabrication prompt and return the
        raw validated dict (pre-normalization).

        Raises:
            ValueError: if the LLM is unconfigured, returns invalid JSON,
                        or fails Pydantic schema validation.
        """
        system_prompt, user_prompt = build_prompt(job_description)

        try:
            raw_result = self._generate_json(
                prompt=user_prompt,
                system_prompt=system_prompt,
            )
        except ValueError:
            raise
        except Exception as e:
            logger.error("LLM call failed during job description extraction: %s", e, exc_info=True)
            raise ValueError(f"LLM extraction failed: {e}") from e

        if not isinstance(raw_result, dict):
            logger.warning(
                "LLM returned unexpected type %s (expected JSON object); attempting one technical retry...",
                type(raw_result).__name__,
            )
            try:
                retry_result = self._generate_json(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                )
                if isinstance(retry_result, dict):
                    raw_result = retry_result
                else:
                    raise ValueError(
                        f"LLM returned unexpected type {type(retry_result).__name__}; expected a JSON object."
                    )
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(
                    f"LLM returned unexpected type {type(raw_result).__name__}; expected a JSON object."
                ) from e

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
