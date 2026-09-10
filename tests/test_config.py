import pytest
from src.core.config import Settings

def test_settings_provider_and_model_parsing():
    settings = Settings()

    # Provider/model format
    provider, model = settings.parse_provider_and_model("groq/llama-3.3-70b-versatile")
    assert provider == "groq"
    assert model == "llama-3.3-70b-versatile"

    provider, model = settings.parse_provider_and_model("openai/gpt-4o-mini")
    assert provider == "openai"
    assert model == "gpt-4o-mini"

    provider, model = settings.parse_provider_and_model("anthropic/claude-3-5-sonnet")
    assert provider == "anthropic"
    assert model == "claude-3-5-sonnet"

    # Standalone model defaults to groq
    provider, model = settings.parse_provider_and_model("mixtral-8x7b-32768")
    assert provider == "groq"
    assert model == "mixtral-8x7b-32768"

def test_settings_api_key_resolution():
    settings = Settings(
        GROQ_API_KEY="groq_key_123",
        OPENAI_API_KEY="openai_key_456",
        ANTHROPIC_API_KEY="anthropic_key_789"
    )
    assert settings.get_api_key("groq") == "groq_key_123"
    assert settings.get_api_key("openai") == "openai_key_456"
    assert settings.get_api_key("anthropic") == "anthropic_key_789"

    # Generic override takes priority
    settings_with_override = Settings(
        LLM_API_KEY="generic_override_key",
        GROQ_API_KEY="groq_key_123"
    )
    assert settings_with_override.get_api_key("groq") == "generic_override_key"
