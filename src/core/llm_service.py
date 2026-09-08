import os
import re
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from functools import lru_cache

from .config import LLMSettings, get_llm_settings

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """Abstract interface for LLM provider implementations."""

    @abstractmethod
    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generates raw text response."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the provider is properly configured with an API key/endpoint."""
        pass


class GeminiProvider(BaseLLMProvider):
    """Google Gemini LLM provider implementation."""

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self._model = None
        if self.settings.api_key:
            self._init_client()

    def _init_client(self):
        try:
            import google.generativeai as genai
            genai.configure(
                api_key=self.settings.api_key,
                client_options={"api_endpoint": self.settings.base_url} if self.settings.base_url else None
            )
            generation_config = {
                "temperature": self.settings.temperature,
                "max_output_tokens": self.settings.max_tokens,
            }
            self._model = genai.GenerativeModel(
                model_name=self.settings.model_name,
                generation_config=generation_config
            )
            logger.info(f"Gemini LLM initialized with model: {self.settings.model_name}")
        except Exception as e:
            logger.warning(f"Failed to initialize Gemini client: {e}")
            self._model = None

    def is_available(self) -> bool:
        return self._model is not None and bool(self.settings.api_key)

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.is_available():
            raise RuntimeError("Gemini provider is not configured with a valid API key.")

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        response = self._model.generate_content(full_prompt)
        return response.text.strip() if response and response.text else ""


class OpenAICompatibleProvider(BaseLLMProvider):
    """
    OpenAI-compatible HTTP provider implementation.
    Supports OpenAI, Azure, Groq, Mistral, DeepSeek, Ollama, vLLM, and LiteLLM proxies.
    """

    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self.base_url = (self.settings.base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = self.settings.api_key

    def is_available(self) -> bool:
        return bool(self.api_key) or ("localhost" in self.base_url or "127.0.0.1" in self.base_url)

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.is_available():
            raise RuntimeError(f"OpenAI-compatible provider ({self.base_url}) is not configured.")

        import requests

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.settings.model_name,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }

        endpoint = f"{self.base_url}/chat/completions"
        response = requests.post(endpoint, json=payload, headers=headers, timeout=60)
        response.raise_for_status()

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


class LLMService:
    """
    Unified, Reusable Centralized LLM Service.
    All AI features in SkillMatch consume this service without hardcoding providers or keys.
    """

    def __init__(self, settings: Optional[LLMSettings] = None):
        self.settings = settings or get_llm_settings()
        self.provider = self._create_provider(self.settings)

    def _create_provider(self, settings: LLMSettings) -> BaseLLMProvider:
        prov = settings.provider.lower().strip()
        if prov in ("gemini", "google"):
            return GeminiProvider(settings)
        elif prov in ("openai", "groq", "mistral", "deepseek", "ollama", "vllm", "custom"):
            return OpenAICompatibleProvider(settings)
        else:
            # Default to OpenAICompatibleProvider if base_url is specified, else Gemini
            if settings.base_url:
                return OpenAICompatibleProvider(settings)
            return GeminiProvider(settings)

    def is_available(self) -> bool:
        """Returns True if the underlying LLM provider is configured and available."""
        return self.provider.is_available()

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generates text from the configured LLM provider."""
        return self.provider.generate_text(prompt=prompt, system_prompt=system_prompt)

    def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates and parses JSON from the LLM provider.
        Automatically removes markdown formatting backticks if present.
        """
        raw_text = self.generate_text(prompt=prompt, system_prompt=system_prompt)
        
        # Clean markdown wrappers (```json ... ```)
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

        # Extract JSON object substring if surrounding text exists
        match = re.search(r"(\{.*\})", cleaned, flags=re.DOTALL)
        if match:
            cleaned = match.group(1)

        return json.loads(cleaned)


@lru_cache()
def get_llm_service() -> LLMService:
    """Returns cached singleton instance of centralized LLM service."""
    return LLMService(get_llm_settings())
