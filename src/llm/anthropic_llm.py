"""Anthropic (Claude) LLM provider."""

from collections.abc import AsyncIterator

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM, LLMResponse


class AnthropicLLM(ILLM):
    """Async LLM client for Anthropic Claude models."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
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
            import anthropic
        except ImportError:
            raise LLMError("anthropic SDK not installed. Run: pip install anthropic")

        # Separate system messages from conversation
        system_content = ""
        conversation: list[dict] = []
        for msg in messages:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                conversation.append(msg)

        try:
            client = anthropic.AsyncAnthropic(api_key=self._api_key)
            kwargs: dict = {
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": conversation,
            }
            if system_content.strip():
                kwargs["system"] = system_content.strip()

            response = await client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise LLMError("Invalid Anthropic API key")
        except anthropic.RateLimitError:
            raise LLMError("Anthropic rate limit exceeded")
        except Exception as e:
            raise LLMError(f"Anthropic API error: {e}")

        content = response.content[0].text if response.content else ""
        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
        }

        return LLMResponse(content=content, model=self._model, usage=usage)

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        try:
            import anthropic
        except ImportError:
            raise LLMError("anthropic SDK not installed. Run: pip install anthropic")

        system_content = ""
        conversation: list[dict] = []
        for msg in messages:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                conversation.append(msg)

        try:
            client = anthropic.AsyncAnthropic(api_key=self._api_key)
            kwargs: dict = {
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": conversation,
            }
            if system_content.strip():
                kwargs["system"] = system_content.strip()

            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.AuthenticationError:
            raise LLMError("Invalid Anthropic API key")
        except anthropic.RateLimitError:
            raise LLMError("Anthropic rate limit exceeded")
        except Exception as e:
            raise LLMError(f"Anthropic stream error: {e}")
