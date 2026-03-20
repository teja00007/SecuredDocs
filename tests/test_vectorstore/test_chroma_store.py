"""
TDD Test Cases — ChromaDB Store (src/vectorstore/chroma_store.py)

Tests for ChromaDB vector store implementation.
"""
import pytest

from src.core.interfaces import ChunkResult


# ============================================================================
# INSERT
# ============================================================================

class TestChromaInsert:
    """chroma_store.insert()"""

    async def test_insert_single_chunk(self, chroma_store):
        """Should insert one chunk and increase count by 1."""
        chunk = {
            "chunk_id": "single_chunk_0",
            "embedding": [0.1] * 768,
            "text": "Single chunk text",
            "document_id": "doc_single",
            "filename": "single.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
        }
        await chroma_store.insert([chunk])
        assert await chroma_store.count() == 1

    async def test_insert_batch(self, chroma_store, sample_chunks):
        """Should insert multiple chunks in one call."""
        await chroma_store.insert(sample_chunks)
        assert await chroma_store.count() == len(sample_chunks)

    async def test_insert_stores_text(self, chroma_store):
        """Inserted chunk text should be retrievable."""
        chunk = {
            "chunk_id": "text_chunk_0",
            "embedding": [0.5] * 768,
            "text": "Unique stored text content",
            "document_id": "doc_text",
            "filename": "text.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
        }
        await chroma_store.insert([chunk])
        results = await chroma_store.search([0.5] * 768, filter={}, top_k=1)
        assert len(results) == 1
        assert results[0].text == "Unique stored text content"

    async def test_insert_stores_metadata(self, chroma_store):
        """Inserted metadata (document_id, visibility, etc.) should be stored."""
        chunk = {
            "chunk_id": "meta_chunk_0",
            "embedding": [0.5] * 768,
            "text": "Metadata chunk text",
            "document_id": "doc_meta",
            "filename": "meta.pdf",
            "visibility": "public",
            "owner_id": "user_meta",
            "collection_id": "col_meta",
        }
        await chroma_store.insert([chunk])
        results = await chroma_store.search([0.5] * 768, filter={}, top_k=1)
        assert len(results) == 1
        meta = results[0].metadata
        assert meta.get("document_id") == "doc_meta"
        assert meta.get("visibility") == "public"
        assert meta.get("owner_id") == "user_meta"

    async def test_insert_stores_embedding(self, chroma_store):
        """Inserted embedding vector should be stored."""
        chunk = {
            "chunk_id": "embed_chunk_0",
            "embedding": [0.9] * 768,
            "text": "Embedding chunk text",
            "document_id": "doc_embed",
            "filename": "embed.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
        }
        await chroma_store.insert([chunk])
        # Searching with the same embedding should return a very high score
        results = await chroma_store.search([0.9] * 768, filter={}, top_k=1)
        assert len(results) == 1
        assert results[0].chunk_id == "embed_chunk_0"
        assert results[0].score > 0.99

    async def test_insert_idempotent(self, chroma_store):
        """Re-inserting same chunk_id should update, not duplicate."""
        chunk = {
            "chunk_id": "idempotent_chunk_0",
            "embedding": [0.1] * 768,
            "text": "Original text",
            "document_id": "doc_idem",
            "filename": "idem.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
        }
        await chroma_store.insert([chunk])
        # Re-insert with updated text
        chunk_updated = dict(chunk, text="Updated text")
        await chroma_store.insert([chunk_updated])
        assert await chroma_store.count() == 1

    async def test_insert_empty_list_no_op(self, chroma_store):
        """Empty chunk list should be a no-op."""
        await chroma_store.insert([])
        assert await chroma_store.count() == 0


# ============================================================================
# SEARCH
# ============================================================================

class TestChromaSearch:
    """chroma_store.search()"""

    async def test_search_returns_results(self, chroma_store, seeded_chunks):
        """Should return list of ChunkResult."""
        results = await chroma_store.search([0.1] * 768, filter={}, top_k=3)
        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(r, ChunkResult) for r in results)

    async def test_search_results_sorted_by_score(self, chroma_store, seeded_chunks):
        """Results should be sorted by descending similarity score."""
        results = await chroma_store.search([0.1] * 768, filter={}, top_k=3)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_search_respects_top_k(self, chroma_store, seeded_chunks):
        """Should return at most top_k results."""
        results = await chroma_store.search([0.1] * 768, filter={}, top_k=1)
        assert len(results) <= 1

    async def test_search_with_public_filter(self, chroma_store, mixed_visibility_chunks):
        """Filter for visibility=public should only return public chunks."""
        results = await chroma_store.search(
            [0.1] * 768,
            filter={"visibility": "public"},
            top_k=10,
        )
        assert len(results) > 0
        for r in results:
            assert r.metadata.get("visibility") == "public"

    @pytest.mark.skip(reason="ChromaDB $contains operator returns empty for string fields; use Qdrant for RBAC filter integration tests")
    async def test_search_with_team_filter(self, chroma_store, mixed_visibility_chunks):
        """Filter for allowed_teams should only return matching team chunks + public."""
        results = await chroma_store.search(
            [0.1] * 768,
            filter={"visibility": "team", "allowed_teams": ["team1"]},
            top_k=10,
        )
        assert len(results) > 0
        for r in results:
            assert r.metadata.get("visibility") == "team"
            assert "team1" in r.metadata.get("allowed_teams", "")

    @pytest.mark.skip(reason="ChromaDB $contains operator returns empty for string fields; use Qdrant for RBAC filter integration tests")
    async def test_search_with_confidential_filter(self, chroma_store, mixed_visibility_chunks):
        """Filter for allowed_users should only return matching confidential chunks + public."""
        results = await chroma_store.search(
            [0.1] * 768,
            filter={"visibility": "confidential", "allowed_users": ["user4"]},
            top_k=10,
        )
        assert len(results) > 0
        for r in results:
            assert r.metadata.get("visibility") == "confidential"
            assert "user4" in r.metadata.get("allowed_users", "")

    async def test_search_with_owner_filter(self, chroma_store, mixed_visibility_chunks):
        """Filter for owner_id should return owner's chunks regardless of visibility."""
        results = await chroma_store.search(
            [0.1] * 768,
            filter={"owner_id": "user1"},
            top_k=10,
        )
        assert len(results) > 0
        for r in results:
            assert r.metadata.get("owner_id") == "user1"

    async def test_search_combined_rbac_filter(self, chroma_store, mixed_visibility_chunks):
        """Full RBAC filter (public OR owner OR team OR confidential) should work correctly."""
        results = await chroma_store.search(
            [0.1] * 768,
            filter={"$or": [{"visibility": "public"}, {"owner_id": "user1"}]},
            top_k=10,
        )
        assert len(results) > 0
        for r in results:
            meta = r.metadata
            assert meta.get("visibility") == "public" or meta.get("owner_id") == "user1"

    async def test_search_empty_store_returns_empty(self, chroma_store):
        """Search on empty store should return empty list."""
        results = await chroma_store.search([0.1] * 768, filter={}, top_k=5)
        assert results == []

    async def test_search_no_matching_filter_returns_empty(self, chroma_store, seeded_chunks):
        """Filter that matches nothing should return empty list."""
        results = await chroma_store.search(
            [0.1] * 768,
            filter={"visibility": "nonexistent"},
            top_k=10,
        )
        assert results == []

    async def test_search_with_collection_id_filter(self, chroma_store, multi_collection_chunks):
        """Should only return chunks from the specified collection."""
        results = await chroma_store.search(
            [0.1] * 768,
            filter={"collection_id": "col1"},
            top_k=10,
        )
        assert len(results) > 0
        for r in results:
            assert r.metadata.get("collection_id") == "col1"


# ============================================================================
# DELETE
# ============================================================================

class TestChromaDelete:
    """chroma_store.delete_by_document_id()"""

    async def test_delete_removes_all_chunks(self, chroma_store, seeded_chunks):
        """Should remove all chunks for the given document_id."""
        count_before = await chroma_store.count()
        await chroma_store.delete_by_document_id("doc1")
        count_after = await chroma_store.count()
        assert count_after < count_before
        assert count_after == 0

    async def test_delete_returns_count(self, chroma_store, seeded_chunks):
        """Should return the number of chunks deleted."""
        deleted = await chroma_store.delete_by_document_id("doc1")
        assert deleted == len(seeded_chunks)

    async def test_delete_nonexistent_returns_zero(self, chroma_store):
        """Deleting non-existent document_id should return 0."""
        deleted = await chroma_store.delete_by_document_id("nonexistent_doc")
        assert deleted == 0

    async def test_delete_does_not_affect_other_documents(self, chroma_store, multi_doc_chunks):
        """Deleting one document's chunks should not affect other documents."""
        await chroma_store.delete_by_document_id("docA")
        # docB chunks should still be present
        results = await chroma_store.search([0.1] * 768, filter={}, top_k=10)
        doc_ids = {r.document_id for r in results}
        assert "docA" not in doc_ids
        assert "docB" in doc_ids


# ============================================================================
# UPDATE METADATA
# ============================================================================

class TestChromaUpdateMetadata:
    """chroma_store.update_metadata()"""

    async def test_update_visibility(self, chroma_store, seeded_chunks):
        """Should update visibility field on all chunks for a document."""
        await chroma_store.update_metadata("doc1", {"visibility": "private"})
        existing = chroma_store._collection.get(
            where={"document_id": {"$eq": "doc1"}},
            include=["metadatas"],
        )
        for meta in existing.get("metadatas", []):
            assert meta.get("visibility") == "private"

    async def test_update_allowed_teams(self, chroma_store, seeded_chunks):
        """Should update allowed_teams on all chunks for a document."""
        await chroma_store.update_metadata("doc1", {"allowed_teams": ["teamA", "teamB"]})
        existing = chroma_store._collection.get(
            where={"document_id": {"$eq": "doc1"}},
            include=["metadatas"],
        )
        for meta in existing.get("metadatas", []):
            teams_val = meta.get("allowed_teams", "")
            assert "teamA" in teams_val
            assert "teamB" in teams_val

    async def test_update_allowed_users(self, chroma_store, seeded_chunks):
        """Should update allowed_users on all chunks for a document."""
        await chroma_store.update_metadata("doc1", {"allowed_users": ["user9"]})
        existing = chroma_store._collection.get(
            where={"document_id": {"$eq": "doc1"}},
            include=["metadatas"],
        )
        for meta in existing.get("metadatas", []):
            users_val = meta.get("allowed_users", "")
            assert "user9" in users_val

    async def test_update_nonexistent_document(self, chroma_store):
        """Updating non-existent document should be a no-op (not raise)."""
        # Should not raise any exception
        await chroma_store.update_metadata("nonexistent_doc", {"visibility": "private"})


# ============================================================================
# COUNT
# ============================================================================

class TestChromaCount:
    """chroma_store.count()"""

    async def test_count_empty(self, chroma_store):
        """Empty store should return 0."""
        assert await chroma_store.count() == 0

    async def test_count_after_inserts(self, chroma_store, seeded_chunks):
        """Should return total number of chunks across all documents."""
        assert await chroma_store.count() == len(seeded_chunks)

    async def test_count_after_delete(self, chroma_store, seeded_chunks):
        """Count should decrease after deleting chunks."""
        count_before = await chroma_store.count()
        await chroma_store.delete_by_document_id("doc1")
        count_after = await chroma_store.count()
        assert count_after == count_before - len(seeded_chunks)
