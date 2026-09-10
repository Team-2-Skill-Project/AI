import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


def resolve_taxonomy_path(raw_path: str | None = None) -> str:
    """Resolves relative taxonomy file paths against repository root to ensure working directory independence."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    if not raw_path:
        return str(base_dir / "docs" / "ai-contract" / "skills_seed.json")
    path_obj = Path(raw_path)
    if path_obj.is_absolute():
        return str(path_obj)
    if path_obj.exists():
        return str(path_obj.resolve())
    resolved = base_dir / path_obj
    return str(resolved)



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
    api_key: str | None = Field(
        default=None,
        description="API key for the LLM service"
    )
    model_name: str = Field(
        default="gemini-3.6-flash",
        description="Target model identifier (e.g. gemini-3.6-flash, gpt-4o-mini, llama-3.1-70b)"
    )
    base_url: str | None = Field(
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
    """General Application & Security Settings."""
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8001)
    environment: str = Field(default="development")
    taxonomy_path: str = Field(default_factory=resolve_taxonomy_path)

    # CORS Settings
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
        ]
    )
    cors_allowed_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "OPTIONS"])
    cors_allowed_headers: list[str] = Field(default_factory=lambda: ["Content-Type", "Authorization", "X-API-Key", "Accept"])
    cors_allow_credentials: bool = Field(default=True)

    # API Protection & Security Settings
    api_key: str | None = Field(default=None)
    enable_api_key_auth: bool = Field(default=False)
    rate_limit_per_minute: int = Field(default=60)
    enable_rate_limiting: bool = Field(default=True)


@lru_cache
def get_llm_settings() -> LLMSettings:
    """Returns cached singleton instance of centralized LLM settings."""
    return LLMSettings.load_from_env()


@lru_cache
def get_app_settings() -> AppSettings:
    """Returns cached singleton instance of app settings."""
    raw_taxonomy = os.getenv("TAXONOMY_PATH", "")

    cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
    if cors_origins_env:
        cors_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
    else:
        cors_origins = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8080",
        ]

    # If "*" is in allowed origins, allow_credentials MUST be False according to CORS specification
    allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() in ("true", "1")
    if "*" in cors_origins:
        allow_credentials = False

    return AppSettings(
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8001")),
        environment=os.getenv("ENVIRONMENT", "development"),
        taxonomy_path=resolve_taxonomy_path(raw_taxonomy) if raw_taxonomy else resolve_taxonomy_path(),
        cors_allowed_origins=cors_origins,
        cors_allowed_methods=[m.strip().upper() for m in os.getenv("CORS_ALLOWED_METHODS", "GET,POST,OPTIONS").split(",") if m.strip()],
        cors_allowed_headers=[h.strip() for h in os.getenv("CORS_ALLOWED_HEADERS", "Content-Type,Authorization,X-API-Key,Accept").split(",") if h.strip()],
        cors_allow_credentials=allow_credentials,
        api_key=os.getenv("SERVICE_API_KEY") or os.getenv("API_KEY") or None,
        enable_api_key_auth=os.getenv("ENABLE_API_KEY_AUTH", "false").lower() in ("true", "1"),
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
        enable_rate_limiting=os.getenv("ENABLE_RATE_LIMITING", "true").lower() in ("true", "1"),
    )


