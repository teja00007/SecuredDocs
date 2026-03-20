"""Google Gemini LLM provider.

Install: pip install google-generativeai
API key: https://aistudio.google.com/app/apikey
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM, LLMResponse


class GeminiLLM(ILLM):
    """Async LLM client for Google Gemini models."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        self._api_key = api_key
        self._model = model

    def get_model_name(self) -> str:
        return self._model

    def _build_contents(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Split system prompt from conversation for the Gemini API."""
        system_parts: list[str] = []
        contents: list[dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})
        system_instruction = "\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        try:
            import google.generativeai as genai
        except ImportError:
            raise LLMError(
                "google-generativeai SDK not installed. Run: pip install google-generativeai"
            )

        genai.configure(api_key=self._api_key)
        system_instruction, contents = self._build_contents(messages)

        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        try:
            model_kwargs: dict = {"model_name": self._model, "generation_config": generation_config}
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction

            model = genai.GenerativeModel(**model_kwargs)
            response = await model.generate_content_async(contents)
        except Exception as e:
            raise LLMError(f"Gemini API error: {e}")

        content = response.text or ""
        usage = response.usage_metadata
        prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
        completion_tokens = getattr(usage, "candidates_token_count", 0) or 0

        return LLMResponse(
            content=content,
            model=self._model,
            usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        )

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        try:
            import google.generativeai as genai
        except ImportError:
            raise LLMError(
                "google-generativeai SDK not installed. Run: pip install google-generativeai"
            )

        genai.configure(api_key=self._api_key)
        system_instruction, contents = self._build_contents(messages)
        generation_config = {"temperature": temperature, "max_output_tokens": max_tokens}

        try:
            model_kwargs: dict = {"model_name": self._model, "generation_config": generation_config}
            if system_instruction:
                model_kwargs["system_instruction"] = system_instruction

            model = genai.GenerativeModel(**model_kwargs)
            async for chunk in await model.generate_content_async(contents, stream=True):
                text = getattr(chunk, "text", None)
                if text:
                    yield text
        except Exception as e:
            raise LLMError(f"Gemini stream error: {e}")
