from __future__ import annotations
"""Central application configuration.

The original CV service and the feature services used two different settings
objects. This module keeps the original ``AppSettings``/``LLMSettings`` API
and adds the feature-service settings behind one shared ``settings`` object.
"""

import os
import logging
import warnings
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def resolve_taxonomy_path(raw_path: str | None = None) -> str:
    """Resolve and validate taxonomy paths from a stable project-root base."""
    default_path = BASE_DIR / "docs" / "ai-contract" / "skills_seed.json"
    if not raw_path or not raw_path.strip():
        candidate = default_path
    else:
        path_obj = Path(raw_path.strip())
        candidate = path_obj if path_obj.is_absolute() else BASE_DIR / path_obj

    candidate = candidate.resolve()
    if not candidate.is_file():
        raise ValueError(f"Invalid TAXONOMY_PATH: '{raw_path or candidate}' does not exist.")
    return str(candidate)


class LLMSettings(BaseModel):
    """Single canonical LLM configuration consumed across all features."""

    provider: str = Field(default="gemini")
    api_key: str | None = Field(default=None)
    model_name: str = Field(default="gemini-3.5-flash")
    base_url: str | None = Field(default=None)
    temperature: float = Field(default=0.0)
    max_tokens: int = Field(default=4096)
    timeout: float = Field(default=60.0)
    max_retries: int = Field(default=2)

    SUPPORTED_PROVIDERS: ClassVar[set[str]] = {
        "gemini",
        "google",
        "openai",
        "groq",
        "anthropic",
        "mistral",
        "deepseek",
        "ollama",
        "vllm",
        "custom",
    }

    @classmethod
    def validate_provider(cls, provider: str) -> str:
        """Return a normalized provider name or fail clearly at the boundary."""
        normalized = (provider or "").strip().lower()
        if normalized not in cls.SUPPORTED_PROVIDERS:
            supported = ", ".join(sorted(cls.SUPPORTED_PROVIDERS))
            raise ValueError(f"Unsupported LLM provider '{provider}'. Supported providers: {supported}")
        return normalized

    @classmethod
    def load_from_env(cls) -> "LLMSettings":
        """Load unified LLM settings from environment variables."""
        load_dotenv(override=True)
        provider = (
            os.getenv("LLM_PROVIDER")
            or ("openai" if os.getenv("OPENAI_API_KEY") and not os.getenv("GEMINI_API_KEY") else "gemini")
        ).lower().strip()

        provider_keys = {
            "gemini": os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            "google": os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
            "openai": os.getenv("OPENAI_API_KEY"),
            "groq": os.getenv("GROQ_API_KEY"),
            "anthropic": os.getenv("ANTHROPIC_API_KEY"),
        }
        # LLM_API_KEY is the intentional generic escape hatch. Provider-specific
        # variables are consulted only for the selected provider.
        api_key = os.getenv("LLM_API_KEY") or provider_keys.get(provider) or None
        if api_key:
            api_key = api_key.strip()

        model_name = (
            os.getenv("LLM_MODEL")
            or os.getenv("LLM_MODEL_NAME")
            or "gemini-3.5-flash"
        ).strip()
        if os.getenv("LLM_MODEL_NAME") and not os.getenv("LLM_MODEL"):
            warnings.warn(
                "LLM_MODEL_NAME is deprecated; use LLM_MODEL instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        # If model_name was supplied as 'provider/model', extract both cleanly
        if "/" in model_name:
            prefix_prov, clean_model = model_name.split("/", 1)
            if not os.getenv("LLM_PROVIDER"):
                provider = prefix_prov.lower().strip()
                model_name = clean_model.strip()
            elif prefix_prov.lower().strip() == provider:
                model_name = clean_model.strip()

        try:
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        except ValueError:
            temperature = 0.0

        try:
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
        except ValueError:
            max_tokens = 4096

        try:
            timeout = float(os.getenv("LLM_TIMEOUT", "60.0"))
        except ValueError:
            timeout = 60.0

        try:
            max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))
        except ValueError:
            max_retries = 2

        base_url = os.getenv("LLM_BASE_URL")
        if base_url:
            base_url = base_url.strip() or None

        return cls(
            provider=provider,
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
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
    """Shared unified settings for matching, interviews, persistence, and workers."""

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

    # Canonical LLM configuration. Runtime code must use this object.
    llm: LLMSettings = Field(default_factory=LLMSettings.load_from_env)
    LLM_ALLOW_REQUEST_OVERRIDES: bool = False

    # Persistence and background processing.
    DATABASE_URL: str = str(BASE_DIR / "skillmatch.db")
    JOOBLE_API_KEY: str | None = None
    JOOBLE_API_BASE_URL: str = "https://eg.jooble.org/api"
    JOOBLE_TIMEOUT: float = Field(default=20.0, gt=0.0)
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
        """Build unified settings from environment variables."""
        llm_cfg = LLMSettings.load_from_env()

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
        database_url = env("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'skillmatch.db'}"

        return cls(
            PROJECT_NAME=env("PROJECT_NAME", "SkillMatch AI Services"),
            VERSION=env("APP_VERSION", "1.0.0"),
            API_V1_STR=env("API_V1_STR", "/api/v1"),
            ENVIRONMENT=env("ENVIRONMENT", "development"),
            CORS_ORIGINS=origins or cls().CORS_ORIGINS,
            LLM_ALLOW_REQUEST_OVERRIDES=env_bool("LLM_ALLOW_REQUEST_OVERRIDES", False),
            llm=llm_cfg,
            DATABASE_URL=database_url,
            JOOBLE_API_KEY=(env("JOOBLE_API_KEY") or None),
            JOOBLE_API_BASE_URL=env("JOOBLE_API_BASE_URL", "https://eg.jooble.org/api") or "https://eg.jooble.org/api",
            JOOBLE_TIMEOUT=env_float("JOOBLE_TIMEOUT", 20.0),
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

    def parse_provider_and_model(
        self,
        model_str: str | None = None,
        provider_str: str | None = None
    ) -> tuple[str, str]:
        """
        Resolve (provider, model_name) cleanly without guessing.
        Priority:
          1. Explicit provider passed as argument
          2. Explicit provider prefix embedded in model_str (e.g. 'openai/gpt-4o')
          3. Global configured LLM_PROVIDER from settings
        """
        canonical_llm = self.llm
        target_model = (model_str or canonical_llm.model_name).strip()

        if provider_str:
            normalized_provider = provider_str.lower().strip()
            # Strip only an explicit prefix for the selected provider. Some
            # providers use a slash inside their model IDs (for example
            # Groq's ``openai/gpt-oss-20b``), which must be preserved.
            prefix = f"{normalized_provider}/"
            if target_model.lower().startswith(prefix):
                target_model = target_model[len(prefix):]
            return normalized_provider, target_model.strip()

        if "/" in target_model:
            prov, model = target_model.split("/", 1)
            return prov.lower().strip(), model.strip()

        return canonical_llm.provider.lower().strip(), target_model

    def get_llm_settings(self) -> LLMSettings:
        """Return an LLMSettings instance matching the unified configuration."""
        return self.llm


settings = Settings.from_env()


@lru_cache
def get_llm_settings() -> LLMSettings:
    """Return the unified LLM settings object."""
    return settings.get_llm_settings()


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
