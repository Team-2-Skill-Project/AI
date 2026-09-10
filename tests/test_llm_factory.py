import pytest
from src.core.llm import get_llm
from src.middleware.llm_middleware import (
    LLMContext,
    set_llm_context,
    reset_llm_context,
    estimate_token_count,
    truncate_to_token_limit
)

from src.core.config import settings

def test_get_llm_default():
    llm = get_llm()
    assert llm is not None
    expected_model = settings.parse_provider_and_model()[1]
    assert llm.model_name in ("llama-3.3-70b-versatile", expected_model)
    assert llm.temperature == 0.3

def test_get_llm_explicit_override():
    llm = get_llm(
        model="groq/llama-3.1-8b-instant",
        temperature=0.7,
        api_key="gsk_test_key"
    )
    assert llm.model_name == "llama-3.1-8b-instant"
    assert llm.temperature == 0.7

def test_get_llm_middleware_context_override():
    token = set_llm_context(
        LLMContext(
            model_name="groq/llama-3.1-8b-instant",
            temperature=0.5,
            api_token="gsk_context_key",
            base_url="http://custom-proxy:8000"
        )
    )
    try:
        llm = get_llm()
        assert llm.model_name == "llama-3.1-8b-instant"
        assert llm.temperature == 0.5
        assert llm.groq_api_base == "http://custom-proxy:8000"
    finally:
        reset_llm_context(token)

def test_token_estimation_and_truncation():
    # Short text
    text = "Hello world"
    assert estimate_token_count(text) > 0
    assert truncate_to_token_limit(text, max_tokens=100) == text

    # Long text truncation
    long_text = "word " * 500
    truncated = truncate_to_token_limit(long_text, max_tokens=20)
    assert len(truncated) < len(long_text)
    assert "truncated" in truncated
