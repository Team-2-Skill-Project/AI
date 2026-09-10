from abc import ABC, abstractmethod
from typing import TypeVar, Type, Optional, Dict, Any
from pydantic import BaseModel
from langchain_core.language_models.chat_models import BaseChatModel

T = TypeVar("T", bound=BaseModel)

class BaseLLMAdapter(ABC):
    """
    Abstract interface for LLM provider adapters.
    Decouples feature chains from specific AI provider SDKs and ensures uniform
    handling of plain text, structured outputs, retries, and token budgets.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Returns the canonical provider identifier (e.g. 'groq', 'openai', 'anthropic')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Returns the active model identifier."""
        pass

    @abstractmethod
    def get_underlying_model(self) -> BaseChatModel:
        """Returns the configured underlying LangChain ChatModel."""
        pass

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        """Executes a completion and returns plain text string."""
        pass

    @abstractmethod
    async def generate_structured(
        self,
        schema: Type[T],
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs: Any
    ) -> T:
        """Executes a completion bound strictly to a Pydantic schema."""
        pass

    def get_model_info(self) -> Dict[str, Any]:
        """Provides metadata about active provider and model parameters."""
        return {
            "provider": self.provider_name,
            "model": self.model_name,
        }
