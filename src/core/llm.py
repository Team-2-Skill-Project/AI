import logging
from typing import Optional, Any
from langchain_core.language_models.chat_models import BaseChatModel
from langchain.chat_models import init_chat_model
from src.core.config import settings
from src.middleware.llm_middleware import get_llm_context

logger = logging.getLogger(__name__)

def get_llm(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_tokens: Optional[int] = None,
    **kwargs: Any
) -> BaseChatModel:
    """
    Factory that instantiates and returns a configured LangChain ChatModel.
    Resolves settings dynamically via a 3-tier hierarchy:
      1. Explicit arguments passed to this function
      2. Dynamic request context from DynamicLLMMiddleware (headers: X-LLM-*)
      3. Global application defaults configured in Settings / .env

    Supports 'provider/model' formats (e.g. 'groq/llama-3.3-70b-versatile',
    'openai/gpt-4o-mini', 'anthropic/claude-3-5-sonnet-latest').
    """
    ctx = get_llm_context()

    # 1. Resolve target model string & provider
    raw_model_str = (
        model
        or (ctx.model_name if ctx and ctx.model_name else None)
        or settings.LLM_MODEL
    )
    provider, model_name = settings.parse_provider_and_model(raw_model_str)

    # 2. Resolve temperature
    if temperature is not None:
        resolved_temp = temperature
    elif ctx and ctx.temperature is not None:
        resolved_temp = ctx.temperature
    else:
        resolved_temp = settings.LLM_TEMPERATURE

    # 3. Resolve base_url
    resolved_base_url = (
        base_url
        or (ctx.base_url if ctx and ctx.base_url else None)
        or settings.LLM_BASE_URL
    )

    # 4. Resolve API key
    resolved_api_key = (
        api_key
        or (ctx.api_token if ctx and ctx.api_token else None)
        or settings.get_api_key(provider)
    )

    # 5. Resolve max_tokens
    resolved_max_tokens = max_tokens or settings.LLM_MAX_TOKENS

    # Build provider-specific invocation parameters
    model_kwargs = dict(kwargs)

    if provider == "groq":
        model_kwargs.setdefault("max_retries", settings.LLM_MAX_RETRIES)
        model_kwargs.setdefault("request_timeout", settings.LLM_TIMEOUT)
        # LangChain validates provider credentials while constructing the
        # client. A placeholder keeps imports, health checks, and unit tests
        # lazy; the real request still fails clearly until a key is configured.
        model_kwargs["groq_api_key"] = resolved_api_key or "not-configured"
        if resolved_base_url:
            model_kwargs["groq_api_base"] = resolved_base_url
    else:
        model_kwargs.setdefault("max_retries", settings.LLM_MAX_RETRIES)
        model_kwargs.setdefault("timeout", settings.LLM_TIMEOUT)
        model_kwargs["api_key"] = resolved_api_key or "not-configured"
        if resolved_base_url:
            model_kwargs["base_url"] = resolved_base_url

    logger.debug(
        f"Initializing LLM: provider={provider}, model={model_name}, "
        f"temp={resolved_temp}, base_url={resolved_base_url}"
    )

    return init_chat_model(
        model=model_name,
        model_provider=provider,
        temperature=resolved_temp,
        max_tokens=resolved_max_tokens,
        **model_kwargs
    )
