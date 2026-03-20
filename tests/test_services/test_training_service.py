"""Tests for TrainingExample export formats and TrainingService helpers."""

import json
import pytest


class TestTrainingExampleExport:
    """Test serialization methods directly (no DB needed)."""

    def _make_example(self, **kwargs):
        """Build a TrainingExample-like object without a DB session."""
        class FakeExample:
            query = "What is RAG?"
            answer = "Retrieval-Augmented Generation."
            corrected_answer = None
            system_prompt = None
            context = None

            def to_openai_jsonl(self):
                from src.models.training import TrainingExample
                return TrainingExample.to_openai_jsonl(self)

            def to_alpaca(self):
                from src.models.training import TrainingExample
                return TrainingExample.to_alpaca(self)

            def to_sharegpt(self):
                from src.models.training import TrainingExample
                return TrainingExample.to_sharegpt(self)

        obj = FakeExample()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        return obj

    def test_openai_jsonl_structure(self):
        ex = self._make_example()
        result = ex.to_openai_jsonl()
        assert "messages" in result
        roles = [m["role"] for m in result["messages"]]
        assert "user" in roles
        assert "assistant" in roles

    def test_openai_jsonl_uses_corrected_answer(self):
        ex = self._make_example(corrected_answer="Better answer")
        result = ex.to_openai_jsonl()
        assistant_msg = next(m for m in result["messages"] if m["role"] == "assistant")
        assert assistant_msg["content"] == "Better answer"

    def test_openai_jsonl_with_system_prompt(self):
        ex = self._make_example(system_prompt="You are a helpful assistant.")
        result = ex.to_openai_jsonl()
        roles = [m["role"] for m in result["messages"]]
        assert roles[0] == "system"
        assert result["messages"][0]["content"] == "You are a helpful assistant."

    def test_alpaca_structure(self):
        ex = self._make_example()
        result = ex.to_alpaca()
        assert "instruction" in result
        assert "input" in result
        assert "output" in result
        assert result["input"] == "What is RAG?"
        assert result["output"] == "Retrieval-Augmented Generation."

    def test_alpaca_uses_corrected_answer(self):
        ex = self._make_example(corrected_answer="Correct!")
        result = ex.to_alpaca()
        assert result["output"] == "Correct!"

    def test_sharegpt_structure(self):
        ex = self._make_example()
        result = ex.to_sharegpt()
        assert "conversations" in result
        froms = [c["from"] for c in result["conversations"]]
        assert "human" in froms
        assert "gpt" in froms

    def test_sharegpt_includes_system_if_present(self):
        ex = self._make_example(system_prompt="Be concise.")
        result = ex.to_sharegpt()
        assert result["conversations"][0]["from"] == "system"

    def test_openai_jsonl_is_valid_json(self):
        ex = self._make_example()
        result = ex.to_openai_jsonl()
        # Should serialize to valid JSON
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        assert "messages" in parsed
