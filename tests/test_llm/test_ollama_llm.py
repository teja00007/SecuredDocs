"""
TDD Test Cases — Ollama LLM (src/llm/ollama_llm.py)

Tests for Ollama local LLM integration.
"""
import pytest

from src.core.exceptions import LLMError
from src.core.interfaces import LLMResponse


class TestOllamaGenerate:
    """ollama_llm.generate()"""

    async def test_generate_returns_llm_response(self, ollama_llm, mock_ollama_server):
        """Should return an LLMResponse object."""
        messages = [{"role": "user", "content": "Hello"}]
        result = await ollama_llm.generate(messages)
        assert isinstance(result, LLMResponse)

    async def test_generate_returns_text(self, ollama_llm, mock_ollama_server):
        """LLMResponse.text should be a non-empty string."""
        messages = [{"role": "user", "content": "Hello"}]
        result = await ollama_llm.generate(messages)
        assert result.content == "This is a test response from the mock Ollama server."

    async def test_generate_returns_model_name(self, ollama_llm, mock_ollama_server):
        """LLMResponse.model should match configured model name."""
        messages = [{"role": "user", "content": "Hello"}]
        result = await ollama_llm.generate(messages)
        assert result.model == "llama3.1:8b"

    async def test_generate_returns_usage(self, ollama_llm, mock_ollama_server):
        """LLMResponse.usage should contain token counts."""
        messages = [{"role": "user", "content": "Hello"}]
        result = await ollama_llm.generate(messages)
        assert "prompt_tokens" in result.usage
        assert "completion_tokens" in result.usage
        assert result.usage["prompt_tokens"] == 10
        assert result.usage["completion_tokens"] == 20

    async def test_generate_passes_messages(self, ollama_llm, mock_ollama_server):
        """Messages list should be sent to Ollama API."""
        messages = [{"role": "user", "content": "Hello"}]
        await ollama_llm.generate(messages)
        mock_ollama_server.assert_called_once()
        _, kwargs = mock_ollama_server.call_args
        payload = kwargs.get("json", {})
        assert payload["messages"] == messages

    async def test_generate_respects_temperature(self, ollama_llm, mock_ollama_server):
        """Temperature parameter should be forwarded to Ollama."""
        messages = [{"role": "user", "content": "Hello"}]
        await ollama_llm.generate(messages, temperature=0.9)
        _, kwargs = mock_ollama_server.call_args
        payload = kwargs.get("json", {})
        assert payload["options"]["temperature"] == 0.9

    async def test_generate_respects_max_tokens(self, ollama_llm, mock_ollama_server):
        """max_tokens should be forwarded to Ollama."""
        messages = [{"role": "user", "content": "Hello"}]
        await ollama_llm.generate(messages, max_tokens=512)
        _, kwargs = mock_ollama_server.call_args
        payload = kwargs.get("json", {})
        assert payload["options"]["num_predict"] == 512

    async def test_generate_system_message_supported(self, ollama_llm, mock_ollama_server):
        """System message should be handled correctly."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        result = await ollama_llm.generate(messages)
        assert isinstance(result, LLMResponse)
        assert result.content == "This is a test response from the mock Ollama server."

    async def test_generate_connection_error_raises_llm_error(self, ollama_llm):
        """If Ollama server is not running, should raise LLMError."""
        messages = [{"role": "user", "content": "Hello"}]
        with pytest.raises(LLMError):
            await ollama_llm.generate(messages)

    @pytest.mark.skip(reason="requires timeout configuration")
    async def test_generate_timeout_raises_llm_error(self, ollama_llm, slow_ollama_server):
        """Request timeout should raise LLMError."""
        pass

    @pytest.mark.xfail(strict=False)
    async def test_generate_empty_messages_raises(self, ollama_llm):
        """Empty messages list should raise ValueError."""
        with pytest.raises(ValueError):
            await ollama_llm.generate([])


class TestOllamaModelName:
    """ollama_llm.get_model_name()"""

    def test_returns_configured_model(self, ollama_llm):
        """Should return the model name from config."""
        assert ollama_llm.get_model_name() == "llama3.1:8b"
