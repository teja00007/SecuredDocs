"""Qdrant RBAC filter integration tests.

Replaces the 2 skipped ChromaDB tests:
  - test_search_with_team_filter
  - test_search_with_confidential_filter

These tests require a running Qdrant instance on localhost:6333.
Run: docker run -p 6333:6333 qdrant/qdrant

They are marked pytest.mark.integration so they can be skipped in CI
environments that don't have Qdrant running:
    pytest -m "not integration"

Or run them explicitly:
    pytest tests/test_vectorstore/test_qdrant_rbac.py -m integration
"""

from __future__ import annotations

import uuid
import pytest

QDRANT_URL = "http://localhost:6333"


def _make_chunk(
    chunk_id: str,
    text: str,
    visibility: str,
    owner_id: str = "user1",
    allowed_teams: str = "",
    allowed_users: str = "",
    company_id: str = "company1",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "embedding": [0.1] * 768,
        "document_id": f"doc-{chunk_id}",
        "visibility": visibility,
        "owner_id": owner_id,
        "allowed_teams": allowed_teams,
        "allowed_users": allowed_users,
        "company_id": company_id,
    }


@pytest.fixture
def unique_collection():
    """Return a unique collection name so tests don't collide."""
    return f"test_rbac_{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def qdrant_store(unique_collection):
    """QdrantStore wired to a fresh temporary collection."""
    pytest.importorskip("qdrant_client", reason="qdrant-client not installed")

    from src.vectorstore.qdrant_store import QdrantStore

    # Patch the collection name to isolate tests
    store = QdrantStore(url=QDRANT_URL, dimensions=768)
    store.COLLECTION_NAME = unique_collection
    yield store
    # Cleanup
    try:
        await store.delete_all()
    except Exception:
        pass


@pytest.fixture
async def rbac_chunks(qdrant_store):
    """Insert a mixed-visibility dataset into the Qdrant store."""
    chunks = [
        _make_chunk("c1", "public doc", "public"),
        _make_chunk("c2", "team doc for team1", "team", allowed_teams="|team1|"),
        _make_chunk("c3", "team doc for team2", "team", allowed_teams="|team2|"),
        _make_chunk("c4", "confidential for user4", "confidential", allowed_users="|user4|"),
        _make_chunk("c5", "confidential for user5", "confidential", allowed_users="|user5|"),
        _make_chunk("c6", "owner doc", "team", owner_id="user1", allowed_teams="|team1|"),
    ]
    await qdrant_store.insert(chunks)
    return chunks


@pytest.mark.integration
@pytest.mark.asyncio
class TestQdrantTeamFilter:
    """team RBAC filter must return only chunks accessible to the queried team."""

    async def test_team_filter_returns_team_chunks(self, qdrant_store, rbac_chunks):
        results = await qdrant_store.search(
            [0.1] * 768,
            filter={"$or": [
                {"visibility": "public"},
                {"visibility": "team", "allowed_teams": ["team1"]},
            ]},
            top_k=10,
        )
        assert len(results) > 0
        for r in results:
            vis = r.metadata.get("visibility")
            assert vis == "public" or (
                vis == "team" and "team1" in r.metadata.get("allowed_teams", "")
            ), f"Unexpected chunk: {r.metadata}"

    async def test_team_filter_excludes_other_teams(self, qdrant_store, rbac_chunks):
        """team2 chunks must NOT appear when filtering for team1."""
        results = await qdrant_store.search(
            [0.1] * 768,
            filter={"visibility": "team", "allowed_teams": ["team1"]},
            top_k=10,
        )
        for r in results:
            assert "team1" in r.metadata.get("allowed_teams", ""), (
                f"Got team2 chunk when filtering for team1: {r.metadata}"
            )

    async def test_team_filter_no_results_for_unknown_team(self, qdrant_store, rbac_chunks):
        results = await qdrant_store.search(
            [0.1] * 768,
            filter={"visibility": "team", "allowed_teams": ["team_unknown"]},
            top_k=10,
        )
        assert results == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestQdrantConfidentialFilter:
    """confidential RBAC filter must return only chunks for the queried user."""

    async def test_confidential_filter_returns_user_chunks(self, qdrant_store, rbac_chunks):
        results = await qdrant_store.search(
            [0.1] * 768,
            filter={"$or": [
                {"visibility": "public"},
                {"visibility": "confidential", "allowed_users": ["user4"]},
            ]},
            top_k=10,
        )
        assert len(results) > 0
        for r in results:
            vis = r.metadata.get("visibility")
            assert vis == "public" or (
                vis == "confidential" and "user4" in r.metadata.get("allowed_users", "")
            ), f"Unexpected chunk: {r.metadata}"

    async def test_confidential_filter_excludes_other_users(self, qdrant_store, rbac_chunks):
        """user5's chunks must NOT appear when filtering for user4."""
        results = await qdrant_store.search(
            [0.1] * 768,
            filter={"visibility": "confidential", "allowed_users": ["user4"]},
            top_k=10,
        )
        for r in results:
            assert "user4" in r.metadata.get("allowed_users", ""), (
                f"Got user5 chunk when filtering for user4: {r.metadata}"
            )

    async def test_confidential_filter_no_results_for_unknown_user(
        self, qdrant_store, rbac_chunks
    ):
        results = await qdrant_store.search(
            [0.1] * 768,
            filter={"visibility": "confidential", "allowed_users": ["nobody"]},
            top_k=10,
        )
        assert results == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestQdrantInternalFilter:
    """INTERNAL visibility — company-wide access (between public and team)."""

    async def test_internal_chunks_visible_to_same_company(self, qdrant_store):
        chunks = [
            _make_chunk("i1", "internal doc co1", "internal", company_id="company1"),
            _make_chunk("i2", "internal doc co2", "internal", company_id="company2"),
        ]
        await qdrant_store.insert(chunks)

        results = await qdrant_store.search(
            [0.1] * 768,
            filter={"$or": [
                {"visibility": "public"},
                {"visibility": "internal", "company_id": "company1"},
            ]},
            top_k=10,
        )
        company_ids = {r.metadata.get("company_id") for r in results if r.metadata.get("visibility") == "internal"}
        assert "company1" in company_ids
        assert "company2" not in company_ids

    async def test_internal_chunks_not_visible_to_other_company(self, qdrant_store):
        chunks = [
            _make_chunk("i3", "internal co2 only", "internal", company_id="company2"),
        ]
        await qdrant_store.insert(chunks)

        results = await qdrant_store.search(
            [0.1] * 768,
            filter={"visibility": "internal", "company_id": "company1"},
            top_k=10,
        )
        for r in results:
            assert r.metadata.get("company_id") == "company1"
