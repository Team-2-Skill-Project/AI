import math
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional, Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


@dataclass
class LLMContext:
    """Stores per-request dynamic LLM configuration."""
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    api_token: Optional[str] = None
    temperature: Optional[float] = None
    provider: Optional[str] = None

# ContextVar to maintain request-scoped LLM configuration safely across async tasks
_current_llm_context: ContextVar[Optional[LLMContext]] = ContextVar("current_llm_context", default=None)

def get_llm_context() -> Optional[LLMContext]:
    """Retrieves the active LLMContext for the current execution context."""
    return _current_llm_context.get()

def set_llm_context(ctx: Optional[LLMContext]):
    """Sets the active LLMContext for the current execution context."""
    return _current_llm_context.set(ctx)

def reset_llm_context(token):
    """Resets the context variable to its previous state."""
    _current_llm_context.reset(token)

class DynamicLLMMiddleware(BaseHTTPMiddleware):
    """
    Middleware that intercepts incoming HTTP requests and extracts dynamic
    LLM parameters from custom headers, making them available to downstream
    LLM clients and chains without hardcoding.

    Supported Headers:
      - X-LLM-Base-Url: Custom endpoint URL (e.g. http://localhost:11434/v1)
      - X-LLM-Model: Dynamic model string (e.g. groq/llama-3.1-8b-instant)
      - X-LLM-Api-Token / X-LLM-Api-Key: Dynamic per-request API token
      - X-LLM-Temperature: Dynamic temperature float (e.g. 0.7)
    """

    def __init__(self, app, allow_overrides: bool = True):
        super().__init__(app)
        self.allow_overrides = allow_overrides

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.allow_overrides:
            return await call_next(request)

        headers = request.headers

        base_url = headers.get("x-llm-base-url")
        model_name = headers.get("x-llm-model")
        provider = headers.get("x-llm-provider")
        api_token = headers.get("x-llm-api-token") or headers.get("x-llm-api-key")

        # Even when explicitly enabled for development, only accept known
        # providers and local endpoints. Production mounts this middleware
        # with allow_overrides=False, so these headers are ignored entirely.
        if provider:
            try:
                from src.core.config import LLMSettings
                provider = LLMSettings.validate_provider(provider)
            except ValueError:
                provider = None
        if base_url and not any(host in base_url.lower() for host in ("localhost", "127.0.0.1", "::1")):
            base_url = None

        temperature_header = headers.get("x-llm-temperature")
        temperature: Optional[float] = None
        if temperature_header:
            try:
                temperature = float(temperature_header)
            except ValueError:
                temperature = None

        has_override = any([base_url, model_name, api_token, temperature is not None])

        if has_override:
            ctx = LLMContext(
                model_name=model_name,
                base_url=base_url,
                api_token=api_token,
                temperature=temperature,
                provider=provider,
            )
            token = _current_llm_context.set(ctx)
            try:
                response = await call_next(request)
                return response
            finally:
                _current_llm_context.reset(token)
        else:
            return await call_next(request)

# --- Token Management & Safety Utilities ---

def estimate_token_count(text: str) -> int:
    """
    Heuristic token estimation: ~4 characters per token for English & code,
    providing a fast and dependency-free safe approximation.
    """
    if not text:
        return 0
    # Average word is ~5 chars + 1 space = 6 chars; average token is ~4 chars.
    return max(1, math.ceil(len(text) / 4.0))

def truncate_to_token_limit(text: str, max_tokens: int, suffix: str = "\n... [Context truncated to fit limit]") -> str:
    """
    Truncates input text if its estimated token count exceeds max_tokens,
    safely fitting within model context windows.
    """
    if not text or max_tokens <= 0:
        return ""

    current_tokens = estimate_token_count(text)
    if current_tokens <= max_tokens:
        return text

    # Approximate max character length based on 4 chars/token
    target_char_count = max(0, (max_tokens * 4) - len(suffix))
    return text[:target_char_count] + suffix
