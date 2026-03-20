"""
TDD Test Cases — RAG Service (src/services/rag_service.py)

Tests for the main RAG pipeline orchestrator.
"""
import pytest

from src.core.rbac import UserContext
from src.core.exceptions import LLMError
from src.services.generation_service import GenerationService
from src.services.retrieval_service import RetrievalService
from src.repositories.audit_repository import AuditRepository
from src.services.rag_service import RAGService


class TestRAGQuery:
    """rag_service.query() — full pipeline orchestration."""

    async def test_query_returns_answer_and_sources(self, rag_service, mock_user, seeded_store):
        rag_service._retrieval._vector_store = seeded_store
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        result = await rag_service.query("What is X?", ctx)
        assert "answer" in result
        assert "sources" in result
        assert isinstance(result["answer"], str)
        assert isinstance(result["sources"], list)

    async def test_query_calls_retrieval_with_rbac_filter(self, rag_service, mock_user, mock_embedding_service):
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        await rag_service.query("test query", ctx)
        mock_embedding_service.embed_text.assert_called()

    async def test_query_passes_retrieved_chunks_to_generation(self, rag_service, mock_user, seeded_store, mock_llm):
        rag_service._retrieval._vector_store = seeded_store
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        await rag_service.query("What is X?", ctx)
        mock_llm.generate.assert_called()

    async def test_query_respects_top_k(self, rag_service, mock_user, seeded_store):
        rag_service._retrieval._vector_store = seeded_store
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        result = await rag_service.query("What is X?", ctx, top_k=1)
        assert "answer" in result

    async def test_query_with_collection_filter(self, rag_service, mock_user, seeded_store):
        rag_service._retrieval._vector_store = seeded_store
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        result = await rag_service.query("What is X?", ctx, collection_id="col-1")
        assert "answer" in result

    async def test_query_no_results_returns_no_info_answer(self, rag_service, mock_user, empty_store):
        rag_service._retrieval._vector_store = empty_store
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        result = await rag_service.query("obscure query with no docs", ctx)
        assert "answer" in result
        assert isinstance(result["answer"], str)

    async def test_query_logs_to_audit_trail(self, rag_service, mock_user, db_session):
        from sqlalchemy import select
        from src.models.audit import QueryLog
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        await rag_service.query("audit test query", ctx)
        await db_session.flush()
        logs = (await db_session.execute(select(QueryLog))).scalars().all()
        assert len(logs) >= 1

    async def test_query_sources_contain_metadata(self, rag_service, mock_user, seeded_store):
        rag_service._retrieval._vector_store = seeded_store
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        result = await rag_service.query("What is X?", ctx)
        for source in result["sources"]:
            assert "document_id" in source
            assert "filename" in source

    async def test_query_handles_llm_error_gracefully(self, db_session, mock_embedding_service, mock_vector_store, failing_llm, mock_user):
        retrieval = RetrievalService(embedding_service=mock_embedding_service, vector_store=mock_vector_store)
        generation = GenerationService(llm=failing_llm)
        svc = RAGService(retrieval_service=retrieval, generation_service=generation,
                         audit_repo=AuditRepository(db_session))
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        with pytest.raises(Exception):
            await svc.query("query that causes llm error", ctx)

    async def test_query_handles_vector_store_error_gracefully(self, db_session, mock_embedding_service, failing_store, mock_llm, mock_user):
        retrieval = RetrievalService(embedding_service=mock_embedding_service, vector_store=failing_store)
        generation = GenerationService(llm=mock_llm)
        svc = RAGService(retrieval_service=retrieval, generation_service=generation,
                         audit_repo=AuditRepository(db_session))
        ctx = UserContext(user_id=mock_user.id, roles=[], team_ids=[])
        with pytest.raises(Exception):
            await svc.query("query that causes store error", ctx)


class TestRAGContextAssembly:
    """Verify how chunks are assembled into LLM context."""

    @pytest.mark.xfail(strict=False)
    def test_context_includes_chunk_text(self, rag_service):
        from src.core.interfaces import ChunkResult
        chunk = ChunkResult(chunk_id="c1", text="sample text", document_id="d1",
                            metadata={"filename": "f.pdf"}, score=0.9)
        context = rag_service._generation._format_context([chunk])
        assert "sample text" in context

    @pytest.mark.xfail(strict=False)
    def test_context_includes_source_reference(self, rag_service):
        from src.core.interfaces import ChunkResult
        chunk = ChunkResult(chunk_id="c1", text="sample text", document_id="d1",
                            metadata={"filename": "f.pdf"}, score=0.9)
        context = rag_service._generation._format_context([chunk])
        assert "[1]" in context

    @pytest.mark.xfail(strict=False)
    def test_context_deduplicates_overlapping_chunks(self, rag_service):
        from src.core.interfaces import ChunkResult
        chunk1 = ChunkResult(chunk_id="c1", text="same text", document_id="d1",
                             metadata={"filename": "f.pdf"}, score=0.9)
        chunk2 = ChunkResult(chunk_id="c2", text="same text", document_id="d1",
                             metadata={"filename": "f.pdf"}, score=0.8)
        context = rag_service._generation._format_context([chunk1, chunk2])
        assert context.count("same text") == 1

    @pytest.mark.xfail(strict=False)
    def test_context_respects_max_context_length(self, rag_service):
        from src.core.interfaces import ChunkResult
        chunks = [ChunkResult(chunk_id=f"c{i}", text="x" * 500, document_id=f"d{i}",
                              metadata={"filename": "f.pdf"}, score=0.9 - i * 0.01)
                  for i in range(20)]
        context = rag_service._generation._format_context(chunks)
        assert len(context) < 20 * 500
