import logging
from typing import TypeVar, Type, Optional, Any
from pydantic import BaseModel
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from src.ai.adapters.base import BaseLLMAdapter
from src.core.llm import get_llm

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

class GroqAdapter(BaseLLMAdapter):
    """Specialized adapter for Groq's high-speed inference engine."""

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs: Any
    ):
        self._model_id = model or "llama-3.3-70b-versatile"
        if not self._model_id.startswith("groq/"):
            full_model = f"groq/{self._model_id}"
        else:
            full_model = self._model_id
            self._model_id = full_model.split("/", 1)[1]

        self._llm: BaseChatModel = get_llm(
            model=full_model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            **kwargs
        )

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def model_name(self) -> str:
        return self._model_id

    def get_underlying_model(self) -> BaseChatModel:
        return self._llm

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        messages = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("user", prompt))
        prompt_tmpl = ChatPromptTemplate.from_messages(messages)
        formatted = prompt_tmpl.format_messages()
        try:
            res = await self._llm.ainvoke(formatted)
            return str(res.content)
        except Exception as e:
            if "rate limit" in str(e).lower() or "429" in str(e) or "groq" in str(type(e)).lower():
                logger.warning(f"Groq rate limit encountered ({e}); falling back to Gemini LLM service...")
                from src.core.llm_service import get_llm_service
                service = get_llm_service()
                if service.is_available():
                    import asyncio
                    return await asyncio.to_thread(service.generate_text, prompt, system_prompt)
            raise

    async def generate_structured(
        self,
        schema: Type[T],
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any
    ) -> T:
        messages = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("user", prompt))
        prompt_tmpl = ChatPromptTemplate.from_messages(messages)
        formatted = prompt_tmpl.format_messages()
        try:
            structured_llm = self._llm.with_structured_output(schema)
            return await structured_llm.ainvoke(formatted)
        except Exception as e:
            if "rate limit" in str(e).lower() or "429" in str(e) or "groq" in str(type(e)).lower():
                logger.warning(f"Groq rate limit encountered ({e}); falling back to Gemini LLM service...")
                from src.core.llm_service import get_llm_service
                service = get_llm_service()
                if service.is_available():
                    import asyncio
                    data = await asyncio.to_thread(service.generate_json, prompt, system_prompt)
                    return schema.model_validate(data)
            raise
