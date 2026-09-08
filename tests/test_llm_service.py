import os
import pytest
from src.core.config import LLMSettings, get_llm_settings
from src.core.llm_service import LLMService, GeminiProvider, OpenAICompatibleProvider
from src.cv_extractor.llm_extractor import LLMExtractor


def test_llm_settings_defaults():
    settings = LLMSettings.load_from_env()
    assert settings.provider in ("gemini", "openai")
    assert settings.model_name is not None
    assert settings.temperature == 0.0
    assert settings.max_tokens >= 1024


def test_llm_provider_switching():
    # 1. Gemini configuration
    gemini_settings = LLMSettings(
        provider="gemini",
        api_key="test_gemini_key",
        model_name="gemini-1.5-pro"
    )
    svc_gemini = LLMService(gemini_settings)
    assert isinstance(svc_gemini.provider, GeminiProvider)
    assert svc_gemini.settings.model_name == "gemini-1.5-pro"

    # 2. OpenAI / Groq configuration
    openai_settings = LLMSettings(
        provider="openai",
        api_key="sk-test-openai-key",
        model_name="gpt-4o-mini",
        base_url="https://api.openai.com/v1"
    )
    svc_openai = LLMService(openai_settings)
    assert isinstance(svc_openai.provider, OpenAICompatibleProvider)
    assert svc_openai.settings.model_name == "gpt-4o-mini"
    assert svc_openai.provider.base_url == "https://api.openai.com/v1"

    # 3. Local Ollama / Custom gateway configuration
    ollama_settings = LLMSettings(
        provider="ollama",
        api_key=None,
        model_name="llama3.2:latest",
        base_url="http://localhost:11434/v1"
    )
    svc_ollama = LLMService(ollama_settings)
    assert isinstance(svc_ollama.provider, OpenAICompatibleProvider)
    assert svc_ollama.provider.base_url == "http://localhost:11434/v1"


def test_feature_layer_decoupled_from_llm():
    # Feature layer consumes LLMService via dependency injection
    mock_settings = LLMSettings(provider="gemini", api_key=None)
    mock_service = LLMService(mock_settings)
    
    # Feature layer uses centralized service without hardcoding API keys or models
    extractor = LLMExtractor(llm_service=mock_service)
    assert extractor.llm_service == mock_service

    # Offline/No-key fallback works cleanly
    extracted = extractor.extract_entities(
        full_text="John Doe\nEmail: john@example.com\nEDUCATION\nBSc Computer Science",
        sections={"header": "John Doe", "education": "BSc Computer Science"}
    )
    assert extracted["name"] == "John Doe"
    assert extracted["email"] == "john@example.com"
