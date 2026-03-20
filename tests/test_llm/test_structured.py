"""Tests for src/llm/structured.py — structured LLM output with Pydantic."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel

from src.core.interfaces import LLMResponse
from src.core.exceptions import LLMError
from src.llm.structured import structured_generate, _extract_json, structured_generate_with_fallback


class SimpleSchema(BaseModel):
    answer: str
    confidence: float


class TestExtractJson:
    def test_extracts_json_block(self):
        text = 'Some text\n```json\n{"a": 1}\n```\nMore text'
        assert _extract_json(text) == '{"a": 1}'

    def test_extracts_bare_json(self):
        text = 'Here is the result: {"x": "hello", "y": 42}'
        result = _extract_json(text)
        assert '"x"' in result

    def test_returns_full_text_if_no_json(self):
        text = "no json here"
        assert _extract_json(text) == "no json here"

    def test_code_block_without_json_label(self):
        text = "```\n{\"z\": true}\n```"
        assert _extract_json(text) == '{"z": true}'


class TestStructuredGenerate:
    def _make_llm(self, content: str):
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=LLMResponse(
            content=content, model="test", usage={"prompt_tokens": 10, "completion_tokens": 20}
        ))
        return llm

    @pytest.mark.asyncio
    async def test_valid_json_response(self):
        llm = self._make_llm('{"answer": "42", "confidence": 0.9}')
        result = await structured_generate(llm, [{"role": "user", "content": "q"}], SimpleSchema)
        assert isinstance(result, SimpleSchema)
        assert result.answer == "42"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_json_in_code_block(self):
        llm = self._make_llm('```json\n{"answer": "hello", "confidence": 0.5}\n```')
        result = await structured_generate(llm, [{"role": "user", "content": "q"}], SimpleSchema)
        assert result.answer == "hello"

    @pytest.mark.asyncio
    async def test_retries_on_invalid_json(self):
        calls = [0]
        async def _generate(messages, temperature=0.0, max_tokens=2048):
            calls[0] += 1
            if calls[0] == 1:
                return LLMResponse(content="not json at all!", model="t", usage={})
            return LLMResponse(content='{"answer": "ok", "confidence": 1.0}', model="t", usage={})
        llm = MagicMock()
        llm.generate = _generate
        result = await structured_generate(llm, [{"role": "user", "content": "q"}], SimpleSchema, max_retries=1)
        assert result.answer == "ok"
        assert calls[0] == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        llm = self._make_llm("invalid json!!!")
        with pytest.raises(LLMError, match="structured_generate failed"):
            await structured_generate(llm, [{"role": "user", "content": "q"}], SimpleSchema, max_retries=0)

    @pytest.mark.asyncio
    async def test_fallback_returns_default_on_failure(self):
        llm = self._make_llm("garbage")
        fallback = SimpleSchema(answer="fallback", confidence=0.0)
        result = await structured_generate_with_fallback(
            llm, [{"role": "user", "content": "q"}], SimpleSchema, fallback, max_retries=0
        )
        assert result.answer == "fallback"
