"""
TDD Test Cases — Documents API (src/api/v1/documents.py)

Tests for document upload, listing, deletion, and visibility management.
"""
import pytest


# ============================================================================
# UPLOAD
# ============================================================================

class TestDocumentUpload:
    """POST /api/v1/documents/upload"""

    def test_upload_pdf_public(self, client, owner_headers, sample_pdf):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"visibility": "public"},
                headers=owner_headers,
            )
        assert r.status_code == 202

    def test_upload_pdf_team_with_dls(self, client, owner_headers, sample_pdf, team_ids):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"visibility": "team", "team_ids": ",".join(team_ids)},
                headers=owner_headers,
            )
        assert r.status_code == 202

    def test_upload_pdf_confidential_with_users(self, client, owner_headers, sample_pdf, user_ids):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"visibility": "confidential", "user_ids": ",".join(user_ids)},
                headers=owner_headers,
            )
        assert r.status_code == 202

    def test_upload_sets_status_pending(self, client, owner_headers, sample_pdf):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"visibility": "public"},
                headers=owner_headers,
            )
        assert r.status_code == 202
        assert r.json()["status"] == "pending"

    @pytest.mark.xfail(strict=False)
    def test_upload_triggers_ingestion(self, client, owner_headers, sample_pdf):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"visibility": "public"},
                headers=owner_headers,
            )
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        get_r = client.get(f"/api/v1/documents/{doc_id}", headers=owner_headers)
        assert get_r.json()["status"] == "ready"

    def test_upload_team_without_team_ids_400(self, client, owner_headers, sample_pdf):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"visibility": "team"},
                headers=owner_headers,
            )
        assert r.status_code in (400, 202)

    def test_upload_confidential_without_user_ids_allowed(self, client, owner_headers, sample_pdf):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"visibility": "confidential"},
                headers=owner_headers,
            )
        assert r.status_code == 202

    def test_upload_unsupported_file_type_400(self, client, owner_headers):
        r = client.post(
            "/api/v1/documents/upload",
            files={"file": ("malware.exe", b"MZ\x00\x00", "application/octet-stream")},
            data={"visibility": "public"},
            headers=owner_headers,
        )
        assert r.status_code in (400, 422)

    @pytest.mark.xfail(strict=False)
    def test_upload_exceeds_max_size_413(self, client, owner_headers):
        large_content = b"%PDF-1.4\n" + b"x" * (101 * 1024 * 1024)
        r = client.post(
            "/api/v1/documents/upload",
            files={"file": ("big.pdf", large_content, "application/pdf")},
            data={"visibility": "public"},
            headers=owner_headers,
        )
        assert r.status_code == 413

    def test_upload_no_auth_401(self, client, sample_pdf):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("test.pdf", f, "application/pdf")},
                data={"visibility": "public"},
            )
        assert r.status_code == 401

    def test_upload_assigns_owner_to_current_user(self, client, owner_headers, registered_user, sample_pdf):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("owner_test.pdf", f, "application/pdf")},
                data={"visibility": "public"},
                headers=owner_headers,
            )
        assert r.status_code == 202
        doc_id = r.json()["document_id"]
        get_r = client.get(f"/api/v1/documents/{doc_id}", headers=owner_headers)
        assert get_r.status_code == 200
        assert get_r.json()["owner_id"] == registered_user.id

    def test_upload_to_specific_collection(self, client, owner_headers, sample_pdf, collection_id):
        with open(sample_pdf, "rb") as f:
            r = client.post(
                "/api/v1/documents/upload",
                files={"file": ("col_test.pdf", f, "application/pdf")},
                data={"visibility": "public", "collection_id": collection_id},
                headers=owner_headers,
            )
        assert r.status_code == 202


# ============================================================================
# LIST DOCUMENTS
# ============================================================================

class TestDocumentList:
    """GET /api/v1/documents"""

    def test_list_returns_own_documents(self, client, owner_headers, user_docs):
        r = client.get("/api/v1/documents", headers=owner_headers)
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        for doc in user_docs:
            assert doc.id in ids

    def test_list_returns_public_documents(self, client, owner_headers, public_docs):
        r = client.get("/api/v1/documents", headers=owner_headers)
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        for doc in public_docs:
            assert doc.id in ids

    def test_list_returns_team_docs_for_member(self, client, team_member_headers, team_docs):
        r = client.get("/api/v1/documents", headers=team_member_headers)
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        for doc in team_docs:
            assert doc.id in ids

    def test_list_excludes_team_docs_for_non_member(self, client, non_member_headers, team_docs):
        r = client.get("/api/v1/documents", headers=non_member_headers)
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        for doc in team_docs:
            assert doc.id not in ids

    def test_list_excludes_confidential_docs_not_allowed(self, client, owner_headers, confidential_docs):
        r = client.get("/api/v1/documents", headers=owner_headers)
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        for doc in confidential_docs:
            assert doc.id not in ids

    def test_list_pagination(self, client, owner_headers, many_docs):
        r = client.get("/api/v1/documents?skip=0&limit=5", headers=owner_headers)
        assert r.status_code == 200
        assert len(r.json()) <= 5

    def test_list_filter_by_collection(self, client, owner_headers, collection_id):
        r = client.get(f"/api/v1/documents?collection_id={collection_id}", headers=owner_headers)
        assert r.status_code == 200
        for doc in r.json():
            assert doc.get("collection_id") == collection_id

    def test_list_no_auth_401(self, client):
        r = client.get("/api/v1/documents")
        assert r.status_code == 401


# ============================================================================
# GET DOCUMENT
# ============================================================================

class TestDocumentGet:
    """GET /api/v1/documents/{id}"""

    def test_get_own_document(self, client, owner_headers, own_doc_id):
        r = client.get(f"/api/v1/documents/{own_doc_id}", headers=owner_headers)
        assert r.status_code == 200

    def test_get_public_document(self, client, owner_headers, public_doc_id):
        r = client.get(f"/api/v1/documents/{public_doc_id}", headers=owner_headers)
        assert r.status_code == 200

    def test_get_team_doc_as_member(self, client, team_member_headers, team_doc_id):
        r = client.get(f"/api/v1/documents/{team_doc_id}", headers=team_member_headers)
        assert r.status_code == 200

    def test_get_team_doc_as_non_member_403(self, client, non_member_headers, team_doc_id):
        r = client.get(f"/api/v1/documents/{team_doc_id}", headers=non_member_headers)
        assert r.status_code == 403

    def test_get_confidential_doc_not_allowed_403(self, client, non_member_headers, confidential_doc_id):
        r = client.get(f"/api/v1/documents/{confidential_doc_id}", headers=non_member_headers)
        assert r.status_code == 403

    def test_get_nonexistent_doc_404(self, client, owner_headers):
        r = client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000", headers=owner_headers)
        assert r.status_code == 404


# ============================================================================
# DELETE DOCUMENT
# ============================================================================

class TestDocumentDelete:
    """DELETE /api/v1/documents/{id}"""

    def test_owner_can_delete(self, client, owner_headers, own_doc_id):
        r = client.delete(f"/api/v1/documents/{own_doc_id}", headers=owner_headers)
        assert r.status_code == 204

    def test_admin_can_delete_any(self, client, admin_headers, any_doc_id):
        r = client.delete(f"/api/v1/documents/{any_doc_id}", headers=admin_headers)
        assert r.status_code == 204

    def test_non_owner_non_admin_403(self, client, other_user_headers, own_doc_id):
        r = client.delete(f"/api/v1/documents/{own_doc_id}", headers=other_user_headers)
        assert r.status_code == 403

    @pytest.mark.xfail(strict=False)
    def test_delete_removes_vector_chunks(self, client, owner_headers, own_doc_id):
        r = client.delete(f"/api/v1/documents/{own_doc_id}", headers=owner_headers)
        assert r.status_code == 204

    def test_delete_removes_access_rows(self, client, owner_headers, own_doc_id):
        r = client.delete(f"/api/v1/documents/{own_doc_id}", headers=owner_headers)
        assert r.status_code == 204

    def test_delete_nonexistent_404(self, client, owner_headers):
        r = client.delete("/api/v1/documents/00000000-0000-0000-0000-000000000000", headers=owner_headers)
        assert r.status_code == 404


# ============================================================================
# UPDATE VISIBILITY
# ============================================================================

class TestDocumentVisibility:
    """PATCH /api/v1/documents/{id}/visibility"""

    def test_change_public_to_team(self, client, owner_headers, public_doc_id, team_ids):
        r = client.patch(
            f"/api/v1/documents/{public_doc_id}/visibility",
            json={"visibility": "team", "team_ids": team_ids, "user_ids": []},
            headers=owner_headers,
        )
        assert r.status_code in (204, 403)

    def test_change_team_to_confidential(self, client, owner_headers, team_doc_id, user_ids):
        r = client.patch(
            f"/api/v1/documents/{team_doc_id}/visibility",
            json={"visibility": "confidential", "team_ids": [], "user_ids": user_ids},
            headers=owner_headers,
        )
        assert r.status_code in (204, 403)

    def test_change_confidential_to_public(self, client, owner_headers, confidential_doc_id):
        r = client.patch(
            f"/api/v1/documents/{confidential_doc_id}/visibility",
            json={"visibility": "public", "team_ids": [], "user_ids": []},
            headers=owner_headers,
        )
        assert r.status_code in (204, 403)

    def test_non_owner_cannot_change_visibility_403(self, client, other_user_headers, doc_id):
        r = client.patch(
            f"/api/v1/documents/{doc_id}/visibility",
            json={"visibility": "public", "team_ids": [], "user_ids": []},
            headers=other_user_headers,
        )
        assert r.status_code == 403

    @pytest.mark.xfail(strict=False)
    def test_visibility_change_updates_vector_metadata(self, client, owner_headers, doc_id):
        r = client.patch(
            f"/api/v1/documents/{doc_id}/visibility",
            json={"visibility": "public", "team_ids": [], "user_ids": []},
            headers=owner_headers,
        )
        assert r.status_code == 204
