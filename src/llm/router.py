"""LLM router with model-prefix routing and fallback chain.

Model-prefix routing
--------------------
Pass a ``model`` string prefixed with a provider tag to bypass the default
provider and target a specific one:

    router.get("gemini:gemini-1.5-flash")   → GeminiLLM
    router.get("openai:gpt-4o")             → OpenAILLM
    router.get("azure:gpt-4o")              → AzureOpenAILLM
    router.get("bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0") → BedrockLLM
    router.get("vllm:mistralai/Mistral-7B") → VLLMProvider
    router.get("ollama:phi4-mini")          → OllamaLLM
    router.get("anthropic:claude-sonnet-4-6") → AnthropicLLM

Fallback chain
--------------
When the primary LLM call fails the router tries each fallback in order:

    from src.llm.router import LLMRouter
    from src.config import get_settings

    router = LLMRouter.from_settings(get_settings())
    llm = router.get()           # returns the default LLM
    llm = router.get("gemini:gemini-2.0-flash")  # override with prefix

    # Generate with automatic fallback
    response = await router.generate_with_fallback(messages)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM, LLMResponse

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)


class RouterLLM(ILLM):
    """Wraps a primary LLM and tries a fallback chain on failure."""

    def __init__(self, primary: ILLM, fallbacks: list[ILLM] | None = None) -> None:
        self._primary = primary
        self._fallbacks: list[ILLM] = fallbacks or []

    def get_model_name(self) -> str:
        return self._primary.get_model_name()

    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        chain = [self._primary] + self._fallbacks
        last_exc: Exception | None = None
        for llm in chain:
            try:
                return await llm.generate(messages, temperature, max_tokens)
            except LLMError as e:
                logger.warning("LLM %s failed (%s); trying next in chain.", llm.get_model_name(), e)
                last_exc = e
        raise LLMError(f"All LLMs in fallback chain failed. Last error: {last_exc}")

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        # Try streaming on the primary; fall back to non-streaming generate on others
        try:
            async for token in self._primary.stream(messages, temperature, max_tokens):
                yield token
            return
        except LLMError as e:
            logger.warning(
                "LLM %s stream failed (%s); falling back to non-streaming chain.",
                self._primary.get_model_name(), e,
            )

        # Fallbacks: use generate() and yield content in one shot
        chain = self._fallbacks
        last_exc: Exception | None = None
        for llm in chain:
            try:
                response = await llm.generate(messages, temperature, max_tokens)
                yield response.content
                return
            except LLMError as exc:
                last_exc = exc
                logger.warning("Fallback LLM %s also failed: %s", llm.get_model_name(), exc)

        raise LLMError(f"All LLMs in fallback chain failed. Last error: {last_exc}")


class LLMRouter:
    """Factory that resolves an ILLM by optional model-prefix string.

    Usage::

        router = LLMRouter.from_settings(settings)
        llm = router.get()                         # default provider
        llm = router.get("openai:gpt-4o-mini")     # prefix override
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings

    # ── Public ────────────────────────────────────────────────────────────────

    def get(self, model_spec: str | None = None) -> ILLM:
        """Return an ILLM for *model_spec* (``provider:model``) or the default."""
        if model_spec and ":" in model_spec:
            provider, model = model_spec.split(":", 1)
            return self._build(provider.lower(), model)
        # No prefix — use configured default
        return self._build(self._settings.LLM_PROVIDER.lower(), self._settings.LLM_MODEL)

    def get_with_fallbacks(self, fallback_specs: list[str] | None = None) -> RouterLLM:
        """Return a RouterLLM wrapping the default + optional fallbacks."""
        primary = self.get()
        fallbacks = [self.get(spec) for spec in (fallback_specs or [])]
        return RouterLLM(primary=primary, fallbacks=fallbacks)

    # ── Class method ─────────────────────────────────────────────────────────

    @classmethod
    def from_settings(cls, settings: "Settings") -> "LLMRouter":
        return cls(settings)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _build(self, provider: str, model: str) -> ILLM:
        s = self._settings
        if provider == "ollama":
            from src.llm.ollama_llm import OllamaLLM
            return OllamaLLM(base_url=s.OLLAMA_BASE_URL, model=model, timeout=180.0)

        if provider == "anthropic":
            from src.llm.anthropic_llm import AnthropicLLM
            return AnthropicLLM(api_key=s.ANTHROPIC_API_KEY, model=model)

        if provider == "openai":
            from src.llm.openai_llm import OpenAILLM
            return OpenAILLM(api_key=s.OPENAI_API_KEY, model=model)

        if provider == "gemini":
            from src.llm.providers.gemini_llm import GeminiLLM
            return GeminiLLM(api_key=s.GEMINI_API_KEY, model=model)

        if provider == "azure":
            from src.llm.providers.azure_openai_llm import AzureOpenAILLM
            return AzureOpenAILLM(
                api_key=s.AZURE_OPENAI_API_KEY,
                endpoint=s.AZURE_OPENAI_ENDPOINT,
                deployment=model,
                api_version=s.AZURE_OPENAI_API_VERSION,
            )

        if provider == "bedrock":
            from src.llm.providers.bedrock_llm import BedrockLLM
            return BedrockLLM(
                model_id=model,
                region=s.AWS_REGION,
                aws_access_key_id=s.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=s.AWS_SECRET_ACCESS_KEY,
            )

        if provider == "vllm":
            from src.llm.providers.vllm_llm import VLLMProvider
            return VLLMProvider(base_url=s.VLLM_BASE_URL, model=model)

        raise LLMError(
            f"Unknown LLM provider prefix: {provider!r}. "
            "Supported: ollama, anthropic, openai, gemini, azure, bedrock, vllm"
        )
