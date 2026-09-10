import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel
from src.ai.adapters.base import BaseLLMAdapter
from src.ai.adapters.groq_adapter import GroqAdapter
from src.ai.adapters.openai_adapter import OpenAIAdapter
from src.ai.adapters.factory import LLMAdapterFactory, get_adapter

class SampleSchema(BaseModel):
    summary: str
    confidence: float

def test_groq_adapter_initialization():
    adapter = GroqAdapter(model="llama-3.3-70b-versatile", temperature=0.2)
    assert adapter.provider_name == "groq"
    assert "llama-3.3-70b-versatile" in adapter.model_name
    info = adapter.get_model_info()
    assert info["provider"] == "groq"

def test_openai_adapter_initialization():
    adapter = OpenAIAdapter(model="gpt-4o-mini", temperature=0.5, api_key="sk-test")
    assert adapter.provider_name == "openai"
    assert "gpt-4o-mini" in adapter.model_name
    info = adapter.get_model_info()
    assert info["provider"] == "openai"

def test_adapter_factory_resolution():
    groq_adapter = LLMAdapterFactory.get_adapter(provider="groq", model="llama-3.1-8b-instant")
    assert isinstance(groq_adapter, GroqAdapter)

    openai_adapter = LLMAdapterFactory.get_adapter(provider="openai", model="gpt-4o")
    assert isinstance(openai_adapter, OpenAIAdapter)

    default_adapter = get_adapter()
    assert isinstance(default_adapter, BaseLLMAdapter)

@pytest.mark.asyncio
async def test_adapter_generate_structured_mock():
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.ainvoke = AsyncMock(return_value=SampleSchema(summary="Matched perfectly", confidence=0.95))
    mock_llm.with_structured_output.return_value = mock_structured

    with patch("src.ai.adapters.groq_adapter.get_llm", return_value=mock_llm):
        adapter = GroqAdapter(model="llama-3.3-70b-versatile")
        res = await adapter.generate_structured(SampleSchema, prompt="Evaluate candidate")
        assert res.summary == "Matched perfectly"
        assert res.confidence == 0.95

@pytest.mark.asyncio
async def test_adapter_generate_text_mock():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "Candidate demonstrates great potential."
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)

    with patch("src.ai.adapters.openai_adapter.get_llm", return_value=mock_llm):
        adapter = OpenAIAdapter(model="gpt-4o-mini")
        text = await adapter.generate_text(prompt="Give summary")
        assert "great potential" in text
