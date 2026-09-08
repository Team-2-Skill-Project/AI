import os
from functools import lru_cache
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class LLMSettings(BaseModel):
    """
    Centralized LLM Configuration.
    Reads provider, API key, model name, base URL, and generation parameters
    from environment variables (.env).
    """
    provider: str = Field(
        default="gemini",
        description="LLM provider name (e.g. gemini, openai, groq, mistral, ollama, custom)"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key for the LLM service"
    )
    model_name: str = Field(
        default="gemini-3.6-flash",
        description="Target model identifier (e.g. gemini-3.6-flash, gpt-4o-mini, llama-3.1-70b)"
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Custom base URL for OpenAI-compatible gateways, local Ollama, vLLM, or LiteLLM proxy"
    )
    temperature: float = Field(
        default=0.0,
        description="Sampling temperature for LLM generation"
    )
    max_tokens: int = Field(
        default=4096,
        description="Maximum tokens for generated responses"
    )

    @classmethod
    def load_from_env(cls) -> "LLMSettings":
        """Loads settings with fallback resolution for environment variable aliases."""
        load_dotenv(override=True)
        provider = (
            os.getenv("LLM_PROVIDER")
            or ("openai" if os.getenv("OPENAI_API_KEY") and not os.getenv("GEMINI_API_KEY") else "gemini")
        ).lower().strip()

        api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GROQ_API_KEY")
            or None
        )
        if api_key:
            api_key = api_key.strip()

        model_name = (
            os.getenv("LLM_MODEL_NAME")
            or ("gpt-4o-mini" if provider == "openai" else "gemini-3.6-flash")
        ).strip()

        base_url = os.getenv("LLM_BASE_URL")
        if base_url:
            base_url = base_url.strip()

        temp_str = os.getenv("LLM_TEMPERATURE", "0.0")
        try:
            temperature = float(temp_str)
        except ValueError:
            temperature = 0.0

        max_tokens_str = os.getenv("LLM_MAX_TOKENS", "4096")
        try:
            max_tokens = int(max_tokens_str)
        except ValueError:
            max_tokens = 4096

        return cls(
            provider=provider,
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens
        )


class AppSettings(BaseModel):
    """General Application Settings."""
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8001)
    environment: str = Field(default="development")
    taxonomy_path: str = Field(default="docs/ai-contract/skills_seed.json")


@lru_cache()
def get_llm_settings() -> LLMSettings:
    """Returns cached singleton instance of centralized LLM settings."""
    return LLMSettings.load_from_env()


@lru_cache()
def get_app_settings() -> AppSettings:
    """Returns cached singleton instance of app settings."""
    return AppSettings(
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8001")),
        environment=os.getenv("ENVIRONMENT", "development"),
        taxonomy_path=os.getenv("TAXONOMY_PATH", "docs/ai-contract/skills_seed.json")
    )
