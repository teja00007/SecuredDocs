"""OpenAI LLM provider."""

from collections.abc import AsyncIterator

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM, LLMResponse


class OpenAILLM(ILLM):
    """Async LLM client for OpenAI models."""

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        self._api_key = api_key
        self._model = model

    def get_model_name(self) -> str:
        return self._model

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        try:
            from openai import AsyncOpenAI, AuthenticationError, RateLimitError
        except ImportError:
            raise LLMError("openai SDK not installed. Run: pip install openai")

        try:
            client = AsyncOpenAI(api_key=self._api_key)
            response = await client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except AuthenticationError:
            raise LLMError("Invalid OpenAI API key")
        except RateLimitError:
            raise LLMError("OpenAI rate limit exceeded")
        except Exception as e:
            raise LLMError(f"OpenAI API error: {e}")

        content = response.choices[0].message.content or ""
        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        }

        return LLMResponse(content=content, model=self._model, usage=usage)

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        try:
            from openai import AsyncOpenAI, AuthenticationError, RateLimitError
        except ImportError:
            raise LLMError("openai SDK not installed. Run: pip install openai")

        try:
            client = AsyncOpenAI(api_key=self._api_key)
            async with await client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            ) as stream:
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta
        except AuthenticationError:
            raise LLMError("Invalid OpenAI API key")
        except RateLimitError:
            raise LLMError("OpenAI rate limit exceeded")
        except Exception as e:
            raise LLMError(f"OpenAI stream error: {e}")
