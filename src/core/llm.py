"""The single LangChain LLM construction boundary for SkillMatch."""

import json
import logging
import re
from typing import Any, Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from src.core.config import LLMSettings, settings
from src.middleware.llm_middleware import get_llm_context

logger = logging.getLogger(__name__)

_CREDENTIAL_PROVIDERS = {"gemini", "google", "openai", "groq", "anthropic", "mistral", "deepseek"}
_LOCAL_PROVIDERS = {"ollama", "vllm"}


def _is_local_endpoint(base_url: str | None) -> bool:
    if not base_url:
        return False
    return any(host in base_url.lower() for host in ("localhost", "127.0.0.1", "::1"))


def parse_json_response(raw_text: str) -> dict[str, Any] | list[Any]:
    """Extract one JSON value from a model response without greedy parsing."""
    if not raw_text or not raw_text.strip():
        raise ValueError("Empty response received from LLM")
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for block in re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE):
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    for idx in (m.start() for m in re.finditer(r"[\{\[]", text)):
        try:
            parsed, _ = decoder.raw_decode(text[idx:])
            return parsed
        except json.JSONDecodeError:
            continue
    repaired = re.sub(r",\s*([\}\]])", r"\1", text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass
    for idx in (m.start() for m in re.finditer(r"[\{\[]", repaired)):
        try:
            parsed, _ = decoder.raw_decode(repaired[idx:])
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

    Explicit arguments are useful for trusted internal composition. Request
    context is only populated when the application explicitly enables the
    override middleware; no provider fallback is performed here.
    """
    ctx = get_llm_context()
    llm_settings = settings.get_llm_settings()

    raw_model = model if model is not None else (ctx.model_name if ctx else None)
    raw_model = raw_model or llm_settings.model_name
    effective_provider = provider or (ctx.provider if ctx else None) or llm_settings.provider
    parsed_provider, model_name = settings.parse_provider_and_model(raw_model, effective_provider)
    parsed_provider = LLMSettings.validate_provider(parsed_provider)

    resolved_temp = (
        temperature
        if temperature is not None
        else (ctx.temperature if ctx and ctx.temperature is not None else llm_settings.temperature)
    )
    resolved_base_url = (
        base_url
        if base_url is not None
        else (ctx.base_url if ctx and ctx.base_url else llm_settings.base_url)
    )
    resolved_api_key = (
        api_key
        if api_key is not None
        else (ctx.api_token if ctx and ctx.api_token else llm_settings.api_key)
    )
    resolved_max_tokens = max_tokens if max_tokens is not None else llm_settings.max_tokens
    resolved_timeout = timeout if timeout is not None else llm_settings.timeout
    resolved_retries = max_retries if max_retries is not None else llm_settings.max_retries

    if parsed_provider in _CREDENTIAL_PROVIDERS and not resolved_api_key:
        raise ValueError(f"LLM_API_KEY is required for provider '{parsed_provider}'")
    if parsed_provider == "custom" and resolved_base_url and not _is_local_endpoint(resolved_base_url) and not resolved_api_key:
        raise ValueError("LLM_API_KEY is required for non-local custom LLM endpoints")

    langchain_provider = {"gemini": "google_genai", "google": "google_genai"}.get(
        parsed_provider, parsed_provider
    )
    model_kwargs = dict(kwargs)
    model_kwargs.setdefault("max_retries", resolved_retries)

    # Keep provider-specific constructor names at this boundary; feature code
    # never needs to know which SDK keyword a provider expects.
    if parsed_provider in ("gemini", "google"):
        model_kwargs.setdefault("timeout", resolved_timeout)
        model_kwargs["google_api_key"] = resolved_api_key
        if resolved_base_url:
            model_kwargs["client_options"] = {"api_endpoint": resolved_base_url}
    elif parsed_provider == "groq":
        model_kwargs.setdefault("request_timeout", resolved_timeout)
        model_kwargs["groq_api_key"] = resolved_api_key
        if resolved_base_url:
            model_kwargs["groq_api_base"] = resolved_base_url
    elif parsed_provider == "anthropic":
        model_kwargs.setdefault("timeout", resolved_timeout)
        model_kwargs["anthropic_api_key"] = resolved_api_key
        if resolved_base_url:
            model_kwargs["base_url"] = resolved_base_url
    else:
        model_kwargs.setdefault("timeout", resolved_timeout)
        if resolved_api_key:
            model_kwargs["api_key"] = resolved_api_key
        if resolved_base_url:
            model_kwargs["base_url"] = resolved_base_url

    logger.debug(
        "Initializing LLM provider=%s model=%s temperature=%s timeout=%s retries=%s",
        parsed_provider,
        model_name,
        resolved_temp,
        resolved_timeout,
        resolved_retries,
    )
    return init_chat_model(
        model=model_name,
        model_provider=langchain_provider,
        temperature=resolved_temp,
        max_tokens=resolved_max_tokens,
        **model_kwargs,
    )
