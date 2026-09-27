from __future__ import annotations
"""The single LangChain LLM construction boundary for SkillMatch."""

import json
import logging
import math
import re
from typing import Any, Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel


from src.core.config import LLMSettings, settings

logger = logging.getLogger(__name__)

_CREDENTIAL_PROVIDERS = {"gemini", "google", "openai", "groq", "anthropic", "mistral", "deepseek"}


def estimate_token_count(text: str) -> int:
    """Heuristic token estimation: ~4 characters per token for English & code."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4.0))


def truncate_to_token_limit(
    text: str, max_tokens: int, suffix: str = "\n... [Context truncated to fit limit]"
) -> str:
    """Truncates input text if its estimated token count exceeds max_tokens."""
    if not text or max_tokens <= 0:
        return ""

    current_tokens = estimate_token_count(text)
    if current_tokens <= max_tokens:
        return text

    target_char_count = max(0, (max_tokens * 4) - len(suffix))
    return text[:target_char_count] + suffix


def parse_json_response(raw_text: str) -> dict[str, Any] | list[Any]:
    """Extract one JSON value from a model response without greedy parsing."""
    if not raw_text or not raw_text.strip():
        raise ValueError("Empty response received from LLM")
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Check markdown blocks first (both raw and trailing-comma repaired)
    for block in re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE):
        clean_block = block.strip()
        try:
            return json.loads(clean_block)
        except json.JSONDecodeError:
            pass
        repaired_block = re.sub(r",\s*([\}\]])", r"\1", clean_block)
        try:
            return json.loads(repaired_block)
        except json.JSONDecodeError:
            pass

    # Check whole text with trailing commas repaired
    repaired = re.sub(r",\s*([\}\]])", r"\1", text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for candidate_text in (repaired, text):
        for idx in (m.start() for m in re.finditer(r"[\{\[]", candidate_text)):
            try:
                parsed, _ = decoder.raw_decode(candidate_text[idx:])
                return parsed
            except json.JSONDecodeError:
                continue

    snippet = text[:200] + ("..." if len(text) > 200 else "")
    raise ValueError(f"Failed to extract valid JSON from LLM response: {snippet}")


def get_llm(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_tokens: Optional[int] = None,
    provider: Optional[str] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Build the configured chat model through one canonical path.

    Configuration source is solely settings.llm (loaded from .env).
    """
    llm_settings = settings.get_llm_settings()

    parsed_provider, model_name = settings.parse_provider_and_model(
        model_str=model, provider_str=provider
    )

    if not parsed_provider or not model_name:
        raise ValueError("LLM service is not configured. Set LLM_PROVIDER, LLM_MODEL, and LLM_API_KEY.")

    parsed_provider = LLMSettings.validate_provider(parsed_provider)

    resolved_temperature = temperature if temperature is not None else llm_settings.temperature
    resolved_api_key = api_key if api_key is not None else llm_settings.api_key
    resolved_base_url = base_url if base_url is not None else llm_settings.base_url
    resolved_max_tokens = max_tokens if max_tokens is not None else llm_settings.max_tokens
    resolved_timeout = timeout if timeout is not None else llm_settings.timeout
    resolved_retries = max_retries if max_retries is not None else llm_settings.max_retries

    if parsed_provider in _CREDENTIAL_PROVIDERS and not resolved_api_key:
        raise ValueError(f"LLM_API_KEY is required for provider '{parsed_provider}'")

    langchain_provider = {"gemini": "google_genai", "google": "google_genai"}.get(
        parsed_provider, parsed_provider
    )
    model_kwargs = dict(kwargs)
    model_kwargs.setdefault("max_retries", resolved_retries)

    if parsed_provider in ("gemini", "google"):
        model_kwargs["timeout"] = resolved_timeout
        if resolved_api_key:
            model_kwargs["google_api_key"] = resolved_api_key
        if resolved_base_url:
            model_kwargs["client_options"] = {"api_endpoint": resolved_base_url}
    elif parsed_provider == "groq":
        model_kwargs["request_timeout"] = resolved_timeout
        if resolved_api_key:
            model_kwargs["groq_api_key"] = resolved_api_key
        if resolved_base_url:
            model_kwargs["groq_api_base"] = resolved_base_url
    else:
        model_kwargs["timeout"] = resolved_timeout
        if resolved_api_key:
            model_kwargs["api_key"] = resolved_api_key
        if resolved_base_url:
            model_kwargs["base_url"] = resolved_base_url

    logger.debug(
        "Initializing LLM provider=%s model=%s temperature=%s timeout=%s retries=%s",
        parsed_provider,
        model_name,
        resolved_temperature,
        resolved_timeout,
        resolved_retries,
    )
    try:
        return init_chat_model(
            model=model_name,
            model_provider=langchain_provider,
            temperature=resolved_temperature,
            max_tokens=resolved_max_tokens,
            **model_kwargs,
        )
    except Exception as exc:
        raise ValueError(
            f"Failed to initialize LLM provider '{parsed_provider}' with model '{model_name}': {exc}"
        ) from exc

