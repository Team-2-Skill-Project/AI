import logging
from typing import TypeVar, Type, Optional, Any
from pydantic import BaseModel
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from src.ai.adapters.base import BaseLLMAdapter
from src.core.llm import get_llm

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

class OpenAIAdapter(BaseLLMAdapter):
    """
    Adapter for OpenAI and OpenAI-compatible inference servers
    (e.g., Ollama, vLLM, LocalAI, Azure OpenAI).
    Supports lazy initialization of the underlying model.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm: Optional[BaseChatModel] = None,
        **kwargs: Any
    ):
        self._model_id = model or "gpt-4o-mini"
        if not self._model_id.startswith("openai/"):
            self._full_model = f"openai/{self._model_id}"
        else:
            self._full_model = self._model_id
            self._model_id = self._full_model.split("/", 1)[1]

        self._temperature = temperature
        self._api_key = api_key
        self._base_url = base_url
        self._kwargs = kwargs
        self._llm = llm

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_id

    def get_underlying_model(self) -> BaseChatModel:
        if self._llm is None:
            self._llm = get_llm(
                model=self._full_model,
                temperature=self._temperature,
                api_key=self._api_key,
                base_url=self._base_url,
                **self._kwargs
            )
        return self._llm

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        llm = self.get_underlying_model()
        messages = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("user", prompt))
        prompt_tmpl = ChatPromptTemplate.from_messages(messages)
        formatted = prompt_tmpl.format_messages()
        res = await llm.ainvoke(formatted)
        return str(res.content)

    async def generate_structured(
        self,
        schema: Type[T],
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any
    ) -> T:
        llm = self.get_underlying_model()
        messages = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("user", prompt))
        prompt_tmpl = ChatPromptTemplate.from_messages(messages)
        formatted = prompt_tmpl.format_messages()
        structured_llm = llm.with_structured_output(schema)
        return await structured_llm.ainvoke(formatted)
