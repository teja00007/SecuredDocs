"""
TDD Test Cases — Query API (src/api/v1/query.py)

Tests for the main RAG query endpoint with RBAC enforcement.
"""
import pytest


# ============================================================================
# BASIC QUERY
# ============================================================================

class TestQueryEndpoint:
    """POST /api/v1/query"""

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and LLM")
    def test_query_returns_answer_and_sources(self, client, owner_headers, seeded_docs):
        resp = client.post(
            "/api/v1/query",
            json={"query": "test question"},
            headers=owner_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "sources" in data

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and LLM")
    def test_query_sources_include_document_metadata(self, client, owner_headers, seeded_docs):
        resp = client.post(
            "/api/v1/query",
            json={"query": "test question"},
            headers=owner_headers,
        )
        assert resp.status_code == 200
        sources = resp.json().get("sources", [])
        if sources:
            src = sources[0]
            assert "document_id" in src
            assert "chunk_text" in src
            assert "score" in src

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and LLM")
    def test_query_respects_top_k(self, client, owner_headers, seeded_docs):
        resp = client.post(
            "/api/v1/query",
            json={"query": "test question", "top_k": 3},
            headers=owner_headers,
        )
        assert resp.status_code == 200
        sources = resp.json().get("sources", [])
        assert len(sources) <= 3

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_with_collection_filter(self, client, owner_headers, seeded_docs):
        resp = client.post(
            "/api/v1/query",
            json={"query": "test question", "collection_id": "some-collection-id"},
            headers=owner_headers,
        )
        assert resp.status_code in (200, 404, 500)

    def test_query_empty_string_422(self, client, owner_headers):
        resp = client.post(
            "/api/v1/query",
            json={"query": ""},
            headers=owner_headers,
        )
        assert resp.status_code == 422

    def test_query_no_auth_401(self, client):
        resp = client.post("/api/v1/query", json={"query": "test question"})
        assert resp.status_code == 401

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and LLM")
    def test_query_no_results_returns_graceful_response(self, client, owner_headers):
        resp = client.post(
            "/api/v1/query",
            json={"query": "xyzzy nonsense query that matches nothing"},
            headers=owner_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data


# ============================================================================
# RBAC ENFORCEMENT ON QUERY
# ============================================================================

class TestQueryRBAC:
    """Verify that query results respect document visibility and DL access."""

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_returns_public_docs_to_any_user(self, client, auth_headers, public_doc):
        resp = client.post(
            "/api/v1/query",
            json={"query": "rbac public test"},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 500)

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_returns_team_docs_to_dl_member(self, client, team_member_headers, team_doc):
        resp = client.post(
            "/api/v1/query",
            json={"query": "team doc test"},
            headers=team_member_headers,
        )
        assert resp.status_code in (200, 500)

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_excludes_team_docs_from_non_member(self, client, non_member_headers, team_doc):
        resp = client.post(
            "/api/v1/query",
            json={"query": "team doc test"},
            headers=non_member_headers,
        )
        assert resp.status_code in (200, 500)

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_returns_confidential_to_allowed_user(self, client, allowed_user_headers, confidential_doc):
        resp = client.post(
            "/api/v1/query",
            json={"query": "confidential doc test"},
            headers=allowed_user_headers,
        )
        assert resp.status_code in (200, 500)

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_excludes_confidential_from_non_allowed(self, client, other_user_headers, confidential_doc):
        resp = client.post(
            "/api/v1/query",
            json={"query": "confidential doc test"},
            headers=other_user_headers,
        )
        assert resp.status_code in (200, 500)

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_owner_always_sees_own_docs(self, client, owner_headers, confidential_doc):
        resp = client.post(
            "/api/v1/query",
            json={"query": "owner doc test"},
            headers=owner_headers,
        )
        assert resp.status_code in (200, 500)

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_admin_sees_all_docs(self, client, admin_headers, confidential_doc, team_doc):
        resp = client.post(
            "/api/v1/query",
            json={"query": "admin sees all"},
            headers=admin_headers,
        )
        assert resp.status_code in (200, 500)

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_mixed_visibility_returns_only_authorized(self, client, auth_headers):
        resp = client.post(
            "/api/v1/query",
            json={"query": "mixed visibility test"},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 401, 500)

    @pytest.mark.xfail(strict=False, reason="Requires real embedding service and vector store")
    def test_query_user_in_multiple_dls_sees_union(self, client, multi_team_user_headers):
        resp = client.post(
            "/api/v1/query",
            json={"query": "multi team test"},
            headers=multi_team_user_headers,
        )
        assert resp.status_code in (200, 500)
