from __future__ import annotations
import pytest
from src.core.config import Settings, LLMSettings, get_llm_settings


def test_settings_provider_and_model_parsing():
    gemini_settings = Settings(
        llm=LLMSettings(provider="gemini", model_name="gemini-3.5-flash")
    )
    provider, model = gemini_settings.parse_provider_and_model("gemini-3.5-flash")
    assert (provider, model) == ("gemini", "gemini-3.5-flash")

    groq_settings = Settings(
        llm=LLMSettings(provider="groq", model_name="mixtral-8x7b-32768", api_key="test-key")
    )
    provider, model = groq_settings.parse_provider_and_model("mixtral-8x7b-32768")
    assert (provider, model) == ("groq", "mixtral-8x7b-32768")

    provider, model = gemini_settings.parse_provider_and_model("openai/gpt-4o-mini")
    assert (provider, model) == ("openai", "gpt-4o-mini")

    provider, model = gemini_settings.parse_provider_and_model("custom-model", provider_str="ollama")
    assert (provider, model) == ("ollama", "custom-model")

    groq_qualified_provider, groq_qualified_model = groq_settings.parse_provider_and_model(
        "openai/gpt-oss-20b", provider_str="groq"
    )
    assert (groq_qualified_provider, groq_qualified_model) == ("groq", "openai/gpt-oss-20b")


def test_settings_has_one_canonical_llm_object():
    llm_cfg = LLMSettings(max_tokens=4096, provider="gemini", model_name="gemini-test", api_key="test-key")
    app_cfg = Settings(llm=llm_cfg)
    assert app_cfg.llm is llm_cfg
    assert app_cfg.get_llm_settings() is llm_cfg
    assert app_cfg.llm.max_tokens == 4096
    assert app_cfg.llm.model_name == "gemini-test"


def test_canonical_api_key_is_stored_only_on_llm_settings():
    app_cfg = Settings(
        llm=LLMSettings(provider="openai", model_name="gpt-test", api_key="generic-key")
    )
    assert app_cfg.llm.api_key == "generic-key"
