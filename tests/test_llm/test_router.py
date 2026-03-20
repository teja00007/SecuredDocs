"""Tests for src/llm/router.py — LLM router with prefix routing and fallbacks."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.exceptions import LLMError
from src.core.interfaces import LLMResponse
from src.llm.router import LLMRouter, RouterLLM


def _make_settings(**kwargs):
    from src.config import Settings
    defaults = dict(
        APP_SECRET_KEY="test",
        LLM_PROVIDER="ollama",
        LLM_MODEL="phi4-mini",
        OLLAMA_BASE_URL="http://localhost:11434",
        OPENAI_API_KEY="sk-test",
        ANTHROPIC_API_KEY="",
        GEMINI_API_KEY="",
        AZURE_OPENAI_API_KEY="",
        AZURE_OPENAI_ENDPOINT="",
        AWS_ACCESS_KEY_ID="",
        AWS_SECRET_ACCESS_KEY="",
        VLLM_BASE_URL="http://localhost:8080/v1",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


class TestLLMRouterPrefixRouting:
    def test_default_returns_ollama(self):
        router = LLMRouter.from_settings(_make_settings())
        llm = router.get()
        assert "phi4-mini" in llm.get_model_name()

    def test_openai_prefix(self):
        router = LLMRouter.from_settings(_make_settings(OPENAI_API_KEY="sk-x"))
        llm = router.get("openai:gpt-4o")
        assert llm.get_model_name() == "gpt-4o"

    def test_anthropic_prefix(self):
        router = LLMRouter.from_settings(_make_settings(ANTHROPIC_API_KEY="sk-ant"))
        llm = router.get("anthropic:claude-sonnet-4-6")
        assert llm.get_model_name() == "claude-sonnet-4-6"

    def test_vllm_prefix(self):
        router = LLMRouter.from_settings(_make_settings())
        llm = router.get("vllm:mistralai/Mistral-7B")
        assert llm.get_model_name() == "mistralai/Mistral-7B"

    def test_unknown_prefix_raises(self):
        router = LLMRouter.from_settings(_make_settings())
        with pytest.raises(LLMError, match="Unknown LLM provider prefix"):
            router.get("fakevendor:some-model")

    def test_no_prefix_uses_configured_provider(self):
        router = LLMRouter.from_settings(
            _make_settings(LLM_PROVIDER="openai", LLM_MODEL="gpt-4o-mini", OPENAI_API_KEY="sk-x")
        )
        llm = router.get()
        assert llm.get_model_name() == "gpt-4o-mini"


class TestRouterLLMFallback:
    @pytest.fixture
    def good_llm(self):
        llm = MagicMock()
        llm.get_model_name.return_value = "good-model"
        llm.generate = AsyncMock(return_value=LLMResponse(
            content="Answer", model="good-model", usage={"prompt_tokens": 10, "completion_tokens": 5}
        ))
        return llm

    @pytest.fixture
    def failing_llm(self):
        llm = MagicMock()
        llm.get_model_name.return_value = "failing-model"
        llm.generate = AsyncMock(side_effect=LLMError("Primary down"))
        llm.stream = AsyncMock(side_effect=LLMError("Primary stream down"))
        return llm

    @pytest.mark.asyncio
    async def test_uses_primary_when_ok(self, good_llm):
        router_llm = RouterLLM(primary=good_llm)
        response = await router_llm.generate([{"role": "user", "content": "Hi"}])
        assert response.content == "Answer"
        good_llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_secondary(self, failing_llm, good_llm):
        router_llm = RouterLLM(primary=failing_llm, fallbacks=[good_llm])
        response = await router_llm.generate([{"role": "user", "content": "Hi"}])
        assert response.content == "Answer"
        good_llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_all_fail(self, failing_llm):
        failing_llm2 = MagicMock()
        failing_llm2.get_model_name.return_value = "also-failing"
        failing_llm2.generate = AsyncMock(side_effect=LLMError("Also down"))
        router_llm = RouterLLM(primary=failing_llm, fallbacks=[failing_llm2])
        with pytest.raises(LLMError, match="All LLMs in fallback chain failed"):
            await router_llm.generate([{"role": "user", "content": "Hi"}])
