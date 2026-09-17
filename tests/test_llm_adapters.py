from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

from src.core.llm import get_llm


def test_canonical_factory_resolves_provider_and_model():
    with patch("src.core.llm.init_chat_model", return_value=MagicMock()) as init_model:
        get_llm(provider="openai", model="gpt-test", api_key="test-key", temperature=0.5)

    kwargs = init_model.call_args.kwargs
    assert kwargs["model_provider"] == "openai"
    assert kwargs["model"] == "gpt-test"
    assert kwargs["api_key"] == "test-key"
    assert kwargs["temperature"] == 0.5


def test_canonical_factory_maps_gemini_provider():
    with patch("src.core.llm.init_chat_model", return_value=MagicMock()) as init_model:
        get_llm(provider="gemini", model="gemini-test", api_key="test-key")

    kwargs = init_model.call_args.kwargs
    assert kwargs["model_provider"] == "google_genai"
    assert kwargs["google_api_key"] == "test-key"


def test_local_provider_does_not_require_api_key():
    with patch("src.core.llm.init_chat_model", return_value=MagicMock()) as init_model:
        get_llm(provider="ollama", model="llama-local", base_url="http://localhost:11434/v1")
    assert init_model.call_args.kwargs["model_provider"] == "ollama"


def test_unknown_provider_fails_clearly():
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        get_llm(provider="unknown-provider", model="test", api_key="test-key")


def test_missing_external_api_key_fails_before_model_creation():
    from src.core import llm as llm_module
    from src.core.config import LLMSettings

    old_settings = llm_module.settings.llm
    llm_module.settings.llm = LLMSettings(provider="gemini", model_name="gemini-test", api_key=None)
    try:
        with pytest.raises(ValueError, match="LLM_API_KEY is required"):
            get_llm()
    finally:
        llm_module.settings.llm = old_settings
