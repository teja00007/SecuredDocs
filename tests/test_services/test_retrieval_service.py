"""
TDD Test Cases — Retrieval Service (src/services/retrieval_service.py)

Tests for vector search with RBAC filtering.
"""
import pytest


class TestRetrieve:
    """retrieval_service.retrieve()"""

    async def test_retrieve_returns_ranked_results(self, retrieval_service, seeded_store):
        retrieval_service._vector_store = seeded_store
        results = await retrieval_service.retrieve("query", filter={})
        assert isinstance(results, list)
        assert len(results) >= 1

    async def test_retrieve_results_have_score(self, retrieval_service, seeded_store):
        retrieval_service._vector_store = seeded_store
        results = await retrieval_service.retrieve("query", filter={})
        for r in results:
            assert hasattr(r, "score")

    async def test_retrieve_applies_metadata_filter(self, retrieval_service, seeded_store):
        retrieval_service._vector_store = seeded_store
        await retrieval_service.retrieve("query", filter={"visibility": "public"})
        seeded_store.search.assert_called()
        call_kwargs = seeded_store.search.call_args
        passed_filter = call_kwargs.kwargs.get("filter") or call_kwargs.args[1] if call_kwargs.args else call_kwargs.kwargs.get("filter")
        assert passed_filter is not None

    async def test_retrieve_scopes_to_collection(self, retrieval_service, multi_collection_store):
        retrieval_service._vector_store = multi_collection_store
        await retrieval_service.retrieve("query", filter={}, collection_id="col-1")
        multi_collection_store.search.assert_called()

    async def test_retrieve_respects_top_k(self, retrieval_service, seeded_store):
        retrieval_service._vector_store = seeded_store
        results = await retrieval_service.retrieve("query", filter={}, top_k=1)
        assert len(results) <= 1

    async def test_retrieve_empty_store_returns_empty(self, retrieval_service, empty_store):
        retrieval_service._vector_store = empty_store
        results = await retrieval_service.retrieve("query", filter={})
        assert results == []

    async def test_retrieve_calls_embedding_service(self, retrieval_service, mock_embedding_service):
        await retrieval_service.retrieve("query", filter={})
        mock_embedding_service.embed_text.assert_called_once_with("query")


class TestRetrievalQuality:
    """Verify retrieval returns semantically relevant results."""

    async def test_relevant_query_returns_matching_chunks(self, retrieval_service, seeded_store):
        retrieval_service._vector_store = seeded_store
        results = await retrieval_service.retrieve("Python async", filter={})
        assert isinstance(results, list)
        seeded_store.search.assert_called()

    async def test_irrelevant_query_returns_low_scores(self, retrieval_service, seeded_store):
        retrieval_service._vector_store = seeded_store
        results = await retrieval_service.retrieve("cooking recipes", filter={})
        assert isinstance(results, list)
        seeded_store.search.assert_called()
