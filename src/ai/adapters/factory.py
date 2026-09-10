import logging
from typing import Optional, Any
from src.ai.adapters.base import BaseLLMAdapter
from src.ai.adapters.groq_adapter import GroqAdapter
from src.ai.adapters.openai_adapter import OpenAIAdapter
from src.core.config import settings
from src.middleware.llm_middleware import get_llm_context

logger = logging.getLogger(__name__)

class LLMAdapterFactory:
    """
    Factory for resolving and instantiating appropriate BaseLLMAdapter instances
    based on explicit args, dynamic request headers, or application configuration.
    """

    @staticmethod
    def get_adapter(
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any
    ) -> BaseLLMAdapter:
        ctx = get_llm_context()

        # 1. Resolve raw model string
        target_model = (
            model
            or (ctx.model_name if ctx and ctx.model_name else None)
            or settings.LLM_MODEL
        )

        resolved_provider, resolved_model = settings.parse_provider_and_model(target_model)
        if provider:
            resolved_provider = provider.lower().strip()

        # 2. Instantiate provider-specific adapter
        if resolved_provider == "openai":
            return OpenAIAdapter(
                model=resolved_model,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url,
                **kwargs
            )
        elif resolved_provider in ("groq", "anthropic"):
            # GroqAdapter wraps Groq models seamlessly
            return GroqAdapter(
                model=resolved_model,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url,
                **kwargs
            )
        else:
            # Fallback to GroqAdapter for other/unspecified providers
            return GroqAdapter(
                model=resolved_model,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url,
                **kwargs
            )

# Convenient module-level helper
def get_adapter(*args: Any, **kwargs: Any) -> BaseLLMAdapter:
    return LLMAdapterFactory.get_adapter(*args, **kwargs)
