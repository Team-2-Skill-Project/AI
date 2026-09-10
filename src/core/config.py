"""Central application configuration.

The original CV service and the feature services used two different settings
objects. This module keeps the original ``AppSettings``/``LLMSettings`` API
and adds the feature-service settings behind one shared ``settings`` object.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def resolve_taxonomy_path(raw_path: str | None = None) -> str:
    """Resolve relative taxonomy paths independently of the working directory."""
    if not raw_path:
        return str(BASE_DIR / "docs" / "ai-contract" / "skills_seed.json")

    path_obj = Path(raw_path)
    if path_obj.is_absolute():
        return str(path_obj)
    if path_obj.exists():
        return str(path_obj.resolve())
    return str(BASE_DIR / path_obj)


class LLMSettings(BaseModel):
    """Configuration consumed by the canonical CV extraction LLM service."""

    provider: str = Field(default="gemini")
    api_key: str | None = Field(default=None)
    model_name: str = Field(default="gemini-3.6-flash")
    base_url: str | None = Field(default=None)
    temperature: float = Field(default=0.0)
    max_tokens: int = Field(default=4096)

    @classmethod
    def load_from_env(cls) -> "LLMSettings":
        """Load the legacy CV-provider settings and compatible aliases."""
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
        model_name = (
            os.getenv("LLM_MODEL_NAME")
            or ("gpt-4o-mini" if provider == "openai" else "gemini-3.6-flash")
        ).strip()

        try:
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        except ValueError:
            temperature = 0.0

        try:
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
        except ValueError:
            max_tokens = 4096

        base_url = os.getenv("LLM_BASE_URL")
        return cls(
            provider=provider,
            api_key=api_key.strip() if api_key else None,
            model_name=model_name,
            base_url=base_url.strip() if base_url else None,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class AppSettings(BaseModel):
    """Settings used by the original CV API and dependency graph."""

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8001)
    environment: str = Field(default="development")
    taxonomy_path: str = Field(default_factory=resolve_taxonomy_path)
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
    cors_allowed_headers: list[str] = Field(
        default_factory=lambda: ["Content-Type", "Authorization", "X-API-Key", "Accept"]
    )
    cors_allow_credentials: bool = Field(default=True)
    api_key: str | None = Field(default=None)
    enable_api_key_auth: bool = Field(default=False)
    rate_limit_per_minute: int = Field(default=60, ge=1)
    enable_rate_limiting: bool = Field(default=True)


class Settings(BaseModel):
    """Shared settings for matching, interviews, persistence, and workers."""

    PROJECT_NAME: str = "SkillMatch AI Services"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ])

    # Unified LLM configuration used by feature chains.
    LLM_MODEL: str = "groq/llama-3.3-70b-versatile"
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_TEMPERATURE: float = Field(default=0.3, ge=0.0, le=2.0)
    LLM_MAX_TOKENS: int = Field(default=2048, ge=1)
    LLM_MAX_RETRIES: int = Field(default=2, ge=0)
    LLM_TIMEOUT: float = Field(default=60.0, gt=0.0)

    # Provider-specific keys.
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GROQ_MODEL: str | None = None

    # Persistence and background processing.
    DATABASE_URL: str = str(BASE_DIR / "skillmatch.db")
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = Field(default=20, ge=1)
    REDIS_SOCKET_TIMEOUT: float = Field(default=2.0, gt=0.0)
    REDIS_CONNECT_TIMEOUT: float = Field(default=2.0, gt=0.0)
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    # Endpoint protection and logging.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = Field(default=60, ge=1)
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1)
    LOG_LEVEL: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables without requiring a plugin."""

        def env(name: str, default: str | None = None) -> str | None:
            value = os.getenv(name)
            return value if value is not None else default

        def env_bool(name: str, default: bool) -> bool:
            value = os.getenv(name)
            if value is None:
                return default
            return value.lower().strip() in {"1", "true", "yes", "on"}

        def env_int(name: str, default: int) -> int:
            try:
                return int(env(name, str(default)) or default)
            except (TypeError, ValueError):
                return default

        def env_float(name: str, default: float) -> float:
            try:
                return float(env(name, str(default)) or default)
            except (TypeError, ValueError):
                return default

        origins_raw = env("CORS_ORIGINS") or env("CORS_ALLOWED_ORIGINS")
        origins = [item.strip() for item in origins_raw.split(",") if item.strip()] if origins_raw else None
        llm_model = env("LLM_MODEL") or env("LLM_MODEL_NAME") or "groq/llama-3.3-70b-versatile"
        database_url = env("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'skillmatch.db'}"

        return cls(
            PROJECT_NAME=env("PROJECT_NAME", "SkillMatch AI Services"),
            VERSION=env("APP_VERSION", "1.0.0"),
            API_V1_STR=env("API_V1_STR", "/api/v1"),
            ENVIRONMENT=env("ENVIRONMENT", "development"),
            CORS_ORIGINS=origins or cls().CORS_ORIGINS,
            LLM_MODEL=llm_model,
            LLM_BASE_URL=env("LLM_BASE_URL"),
            LLM_API_KEY=env("LLM_API_KEY"),
            LLM_TEMPERATURE=env_float("LLM_TEMPERATURE", 0.3),
            LLM_MAX_TOKENS=env_int("LLM_MAX_TOKENS", 2048),
            LLM_MAX_RETRIES=env_int("LLM_MAX_RETRIES", 2),
            LLM_TIMEOUT=env_float("LLM_TIMEOUT", 60.0),
            GROQ_API_KEY=env("GROQ_API_KEY", "") or "",
            OPENAI_API_KEY=env("OPENAI_API_KEY", "") or "",
            ANTHROPIC_API_KEY=env("ANTHROPIC_API_KEY", "") or "",
            GEMINI_API_KEY=env("GEMINI_API_KEY", "") or "",
            GROQ_MODEL=env("GROQ_MODEL"),
            DATABASE_URL=database_url,
            REDIS_URL=env("REDIS_URL", "redis://localhost:6379/0"),
            REDIS_MAX_CONNECTIONS=env_int("REDIS_MAX_CONNECTIONS", 20),
            REDIS_SOCKET_TIMEOUT=env_float("REDIS_SOCKET_TIMEOUT", 2.0),
            REDIS_CONNECT_TIMEOUT=env_float("REDIS_CONNECT_TIMEOUT", 2.0),
            CELERY_BROKER_URL=env("CELERY_BROKER_URL"),
            CELERY_RESULT_BACKEND=env("CELERY_RESULT_BACKEND"),
            RATE_LIMIT_ENABLED=env_bool("RATE_LIMIT_ENABLED", True),
            RATE_LIMIT_REQUESTS=env_int("RATE_LIMIT_REQUESTS", 60),
            RATE_LIMIT_WINDOW_SECONDS=env_int("RATE_LIMIT_WINDOW_SECONDS", 60),
            LOG_LEVEL=env("LOG_LEVEL", "INFO"),
        )

    def parse_provider_and_model(self, model_str: str | None = None) -> tuple[str, str]:
        """Split ``provider/model`` identifiers, defaulting bare models to Groq."""
        target = (model_str or self.LLM_MODEL).strip()
        if "/" in target:
            provider, model = target.split("/", 1)
            if provider.lower() in {"groq", "openai", "anthropic"}:
                return provider.lower(), model.strip()
        return "groq", target

    def get_api_keys(self, provider: str) -> list[str]:
        """Return configured keys in priority order for the requested provider."""
        keys: list[str] = []
        if self.LLM_API_KEY:
            keys.extend(key.strip() for key in self.LLM_API_KEY.split(",") if key.strip())

        provider_key = {
            "groq": self.GROQ_API_KEY,
            "openai": self.OPENAI_API_KEY,
            "anthropic": self.ANTHROPIC_API_KEY,
            "gemini": self.GEMINI_API_KEY,
            "google": self.GEMINI_API_KEY,
        }.get(provider.lower().strip(), "")
        for key in provider_key.split(","):
            key = key.strip()
            if key and key not in keys:
                keys.append(key)

        for env_name in ("GROQ_API_KEY_SECONDARY", "OPENAI_API_KEY_SECONDARY", "LLM_API_KEY_FALLBACK"):
            fallback = os.getenv(env_name, "").strip()
            if fallback and fallback not in keys:
                keys.append(fallback)
        return keys

    def get_api_key(self, provider: str) -> str:
        """Return the first configured key for a provider."""
        keys = self.get_api_keys(provider)
        return keys[0] if keys else ""


settings = Settings.from_env()


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings.load_from_env()


@lru_cache
def get_app_settings() -> AppSettings:
    """Return the original CV API settings object."""
    raw_taxonomy = os.getenv("TAXONOMY_PATH", "")
    origins_raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = [item.strip() for item in origins_raw.split(",") if item.strip()] if origins_raw else AppSettings().cors_allowed_origins
    allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() in {"true", "1", "yes", "on"}
    if "*" in origins:
        allow_credentials = False

    return AppSettings(
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8001")),
        environment=os.getenv("ENVIRONMENT", "development"),
        taxonomy_path=resolve_taxonomy_path(raw_taxonomy) if raw_taxonomy else resolve_taxonomy_path(),
        cors_allowed_origins=origins,
        cors_allowed_methods=[m.strip().upper() for m in os.getenv("CORS_ALLOWED_METHODS", "GET,POST,OPTIONS").split(",") if m.strip()],
        cors_allowed_headers=[h.strip() for h in os.getenv("CORS_ALLOWED_HEADERS", "Content-Type,Authorization,X-API-Key,Accept").split(",") if h.strip()],
        cors_allow_credentials=allow_credentials,
        api_key=os.getenv("SERVICE_API_KEY") or os.getenv("API_KEY") or None,
        enable_api_key_auth=os.getenv("ENABLE_API_KEY_AUTH", "false").lower() in {"true", "1", "yes", "on"},
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
        enable_rate_limiting=os.getenv("ENABLE_RATE_LIMITING", "true").lower() in {"true", "1", "yes", "on"},
    )
