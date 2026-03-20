"""Azure OpenAI LLM provider.

Install: pip install openai  (already a dependency)
Requires env vars:
    AZURE_OPENAI_ENDPOINT  — e.g. https://<resource>.openai.azure.com/
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_API_VERSION — e.g. 2024-02-01
    LLM_MODEL              — the *deployment name* in Azure (e.g. "gpt-4o")
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM, LLMResponse


class AzureOpenAILLM(ILLM):
    """Async LLM client for Azure-hosted OpenAI models."""

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        deployment: str,
        api_version: str = "2024-02-01",
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._api_version = api_version

    def get_model_name(self) -> str:
        return f"azure/{self._deployment}"

    def _make_client(self):
        try:
            from openai import AsyncAzureOpenAI
        except ImportError:
            raise LLMError("openai SDK not installed. Run: pip install openai")
        return AsyncAzureOpenAI(
            api_key=self._api_key,
            azure_endpoint=self._endpoint,
            api_version=self._api_version,
        )

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        try:
            from openai import AuthenticationError, RateLimitError
        except ImportError:
            raise LLMError("openai SDK not installed. Run: pip install openai")

        client = self._make_client()
        try:
            response = await client.chat.completions.create(
                model=self._deployment,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except AuthenticationError:
            raise LLMError("Invalid Azure OpenAI API key or endpoint")
        except RateLimitError:
            raise LLMError("Azure OpenAI rate limit exceeded")
        except Exception as e:
            raise LLMError(f"Azure OpenAI API error: {e}")

        content = response.choices[0].message.content or ""
        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        }
        return LLMResponse(content=content, model=self.get_model_name(), usage=usage)

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        try:
            from openai import AuthenticationError, RateLimitError
        except ImportError:
            raise LLMError("openai SDK not installed. Run: pip install openai")

        client = self._make_client()
        try:
            async with await client.chat.completions.create(
                model=self._deployment,
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
            raise LLMError("Invalid Azure OpenAI API key or endpoint")
        except RateLimitError:
            raise LLMError("Azure OpenAI rate limit exceeded")
        except Exception as e:
            raise LLMError(f"Azure OpenAI stream error: {e}")
