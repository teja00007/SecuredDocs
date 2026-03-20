"""Fixtures for LLM tests."""
import pytest

from src.llm.ollama_llm import OllamaLLM


@pytest.fixture
def ollama_llm():
    """OllamaLLM instance pointing at localhost (may not be running in CI)."""
    return OllamaLLM(base_url="http://localhost:11434", model="llama3.1:8b")


@pytest.fixture
def mock_ollama_server(monkeypatch):
    """Mock Ollama HTTP server that returns a canned response."""
    from unittest.mock import AsyncMock, MagicMock
    import httpx

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {"content": "This is a test response from the mock Ollama server."},
        "model": "llama3.1:8b",
        "prompt_eval_count": 10,
        "eval_count": 20,
    }
    mock_response.raise_for_status = MagicMock()

    mock_post = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    return mock_post


@pytest.fixture
def slow_ollama_server(monkeypatch):
    """Mock Ollama server that simulates a timeout by sleeping indefinitely."""
    import asyncio
    from unittest.mock import AsyncMock

    async def _slow_post(*args, **kwargs):
        await asyncio.sleep(9999)

    mock_post = AsyncMock(side_effect=_slow_post)
    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    return mock_post
