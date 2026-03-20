"""Ollama LLM provider — calls local Ollama server via HTTP."""

import json
from collections.abc import AsyncIterator

import httpx

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM, LLMResponse


class OllamaLLM(ILLM):
    """Async LLM client for locally running Ollama models."""

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def get_model_name(self) -> str:
        return self._model

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError:
            raise LLMError(f"Cannot connect to Ollama at {self._base_url}. Is Ollama running?")
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama API error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise LLMError(f"Ollama request failed: {e}")

        message = data.get("message", {})
        content = message.get("content", "")

        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }

        return LLMResponse(content=content, model=self._model, usage=usage)

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if data.get("done"):
                            break
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
        except httpx.ConnectError:
            raise LLMError(f"Cannot connect to Ollama at {self._base_url}. Is Ollama running?")
        except httpx.HTTPStatusError as e:
            # Cannot access e.response.text on a streaming response without reading first
            raise LLMError(f"Ollama API error {e.response.status_code}")

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        url = f"{self._base_url}/api/embeddings"
        payload = {"model": self._model, "prompt": text}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError:
            raise LLMError(f"Cannot connect to Ollama at {self._base_url}")
        except Exception as e:
            raise LLMError(f"Ollama embed request failed: {e}")

        return data.get("embedding", [])
