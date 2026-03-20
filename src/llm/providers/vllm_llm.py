"""vLLM LLM provider — calls a self-hosted vLLM server via its OpenAI-compatible API.

vLLM exposes an OpenAI-compatible /v1/chat/completions endpoint so we can
reuse the openai SDK with a custom base_url.

Quickstart (server side):
    pip install vllm
    python -m vllm.entrypoints.openai.api_server \\
        --model mistralai/Mistral-7B-Instruct-v0.2 \\
        --host 0.0.0.0 --port 8080

Config:
    LLM_PROVIDER=vllm
    VLLM_BASE_URL=http://localhost:8080/v1
    LLM_MODEL=mistralai/Mistral-7B-Instruct-v0.2   # must match server
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM, LLMResponse


class VLLMProvider(ILLM):
    """Async LLM client for a vLLM server (OpenAI-compatible REST API)."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080/v1",
        model: str = "mistralai/Mistral-7B-Instruct-v0.2",
        api_key: str = "vllm",          # vLLM ignores the key; openai SDK requires one
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    def get_model_name(self) -> str:
        return self._model

    def _make_client(self):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise LLMError("openai SDK not installed. Run: pip install openai")
        return AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        client = self._make_client()
        try:
            response = await client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            raise LLMError(f"vLLM API error: {e}")

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
        client = self._make_client()
        try:
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
        except Exception as e:
            raise LLMError(f"vLLM stream error: {e}")
