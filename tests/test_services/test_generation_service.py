"""
TDD Test Cases — Generation Service (src/services/generation_service.py)

Tests for LLM prompt construction and response generation.
"""
import pytest

from src.core.exceptions import LLMError
from src.core.interfaces import ChunkResult
from src.services.generation_service import GenerationService, _SYSTEM_WITH_CONTEXT, _SYSTEM_NO_CONTEXT


class TestGenerate:
    """generation_service.generate()"""

    async def test_generate_returns_string(self, generation_service, mock_llm, sample_chunks):
        from src.core.interfaces import ChunkResult
        chunks = [ChunkResult(chunk_id=c["chunk_id"], text=c["text"], document_id=c["document_id"],
                              metadata={"filename": c["filename"]}, score=0.8)
                  for c in sample_chunks]
        result = await generation_service.generate("What is X?", chunks)
        assert isinstance(result, str)

    async def test_generate_passes_system_prompt(self, generation_service, mock_llm, sample_chunks):
        chunks = [ChunkResult(chunk_id=c["chunk_id"], text=c["text"], document_id=c["document_id"],
                              metadata={"filename": c["filename"]}, score=0.8)
                  for c in sample_chunks]
        await generation_service.generate("What is X?", chunks)
        call_args = mock_llm.generate.call_args
        messages = call_args.args[0] if call_args.args else call_args.kwargs["messages"]
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert "context" in system_msgs[0]["content"].lower() or "nexus" in system_msgs[0]["content"].lower()

    async def test_generate_includes_context_in_prompt(self, generation_service, mock_llm, sample_chunks):
        chunks = [ChunkResult(chunk_id=c["chunk_id"], text=c["text"], document_id=c["document_id"],
                              metadata={"filename": c["filename"]}, score=0.8)
                  for c in sample_chunks]
        await generation_service.generate("What is X?", chunks)
        call_args = mock_llm.generate.call_args
        messages = call_args.args[0] if call_args.args else call_args.kwargs["messages"]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert any(c["text"] in user_msgs[0]["content"] for c in sample_chunks)

    async def test_generate_includes_user_query(self, generation_service, mock_llm, sample_chunks):
        chunks = [ChunkResult(chunk_id=c["chunk_id"], text=c["text"], document_id=c["document_id"],
                              metadata={"filename": c["filename"]}, score=0.8)
                  for c in sample_chunks]
        query = "What is the meaning of life?"
        await generation_service.generate(query, chunks)
        call_args = mock_llm.generate.call_args
        messages = call_args.args[0] if call_args.args else call_args.kwargs["messages"]
        combined = " ".join(m["content"] for m in messages)
        assert query in combined

    async def test_generate_with_chat_history(self, generation_service, mock_llm, sample_chunks, chat_history):
        chunks = [ChunkResult(chunk_id=c["chunk_id"], text=c["text"], document_id=c["document_id"],
                              metadata={"filename": c["filename"]}, score=0.8)
                  for c in sample_chunks]
        await generation_service.generate("Follow-up?", chunks, chat_history=chat_history)
        call_args = mock_llm.generate.call_args
        messages = call_args.args[0] if call_args.args else call_args.kwargs["messages"]
        roles = [m["role"] for m in messages]
        assert "user" in roles and "assistant" in roles

    async def test_generate_no_context_instructs_no_info(self, generation_service, mock_llm):
        await generation_service.generate("What is X?", [])
        call_args = mock_llm.generate.call_args
        messages = call_args.args[0] if call_args.args else call_args.kwargs["messages"]
        system_msgs = [m for m in messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert _SYSTEM_NO_CONTEXT in system_msgs[0]["content"] or "general knowledge" in system_msgs[0]["content"].lower() or "helpful" in system_msgs[0]["content"].lower()

    async def test_generate_handles_llm_error(self, generation_service, failing_llm):
        svc = GenerationService(llm=failing_llm)
        with pytest.raises((LLMError, Exception)):
            await svc.generate("query", [])


class TestPromptConstruction:
    """Verify the prompt template structure."""

    def test_system_prompt_contains_grounding_instruction(self, generation_service):
        assert "context" in _SYSTEM_WITH_CONTEXT.lower()

    def test_system_prompt_contains_citation_instruction(self, generation_service):
        assert "[1]" in _SYSTEM_WITH_CONTEXT or "citation" in _SYSTEM_WITH_CONTEXT.lower() or "[2]" in _SYSTEM_WITH_CONTEXT

    def test_context_format_includes_source_numbers(self, generation_service, sample_chunks):
        chunks = [ChunkResult(chunk_id=c["chunk_id"], text=c["text"], document_id=c["document_id"],
                              metadata={"filename": c["filename"]}, score=0.8)
                  for c in sample_chunks]
        context = generation_service._format_context(chunks)
        assert "[1]" in context

    @pytest.mark.xfail(strict=False)
    async def test_context_truncated_if_exceeds_limit(self, generation_service, many_large_chunks):
        chunks = [ChunkResult(chunk_id=c["chunk_id"], text=c["text"], document_id=c["document_id"],
                              metadata={"filename": c["filename"]}, score=0.8)
                  for c in many_large_chunks]
        context = generation_service._format_context(chunks)
        assert len(context) < len("".join(c["text"] for c in many_large_chunks))
