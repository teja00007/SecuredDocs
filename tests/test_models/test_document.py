"""
TDD Test Cases — Document Models (src/models/document.py)

Tests for Collection, Document, DocumentTeamAccess, DocumentUserAccess ORM models.
"""
import pytest
import uuid as uuid_mod

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.user import User
from src.models.team import Team
from src.models.document import (
    Collection, Document, DocumentTeamAccess, DocumentUserAccess,
    VisibilityEnum, DocumentStatusEnum,
)
from src.core.security import hash_password


# ============================================================================
# COLLECTION MODEL
# ============================================================================

class TestCollectionModel:
    """Verify Collection ORM model behavior."""

    @pytest.mark.asyncio
    async def test_create_collection(self, db_session):
        """Should create collection with name, description, owner_id."""
        user = User(username="col_u", email="col@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        col = Collection(name="Test Col", description="desc", owner_id=user.id)
        db_session.add(col)
        await db_session.commit()
        await db_session.refresh(col)
        assert col.name == "Test Col"

    @pytest.mark.asyncio
    async def test_collection_id_is_uuid(self, db_session):
        """Collection.id should be auto-generated UUID."""
        user = User(username="col_uuid", email="cu@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        col = Collection(name="UUID Col", owner_id=user.id)
        db_session.add(col)
        await db_session.commit()
        await db_session.refresh(col)
        parsed = uuid_mod.UUID(col.id)
        assert str(parsed) == col.id

    @pytest.mark.asyncio
    async def test_collection_owner_relationship(self, db_session):
        """collection.owner should return the User who created it."""
        user = User(username="col_own", email="co@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        col = Collection(name="Owner Col", owner_id=user.id)
        db_session.add(col)
        await db_session.commit()
        await db_session.refresh(col)
        assert col.owner.username == "col_own"

    @pytest.mark.asyncio
    async def test_collection_documents_relationship(self, db_session):
        """collection.documents should return list of Documents in it."""
        user = User(username="col_doc", email="cd@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        col = Collection(name="Doc Col", owner_id=user.id)
        db_session.add(col)
        await db_session.flush()
        doc = Document(filename="f.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(col)
        assert len(col.documents) == 1

    @pytest.mark.asyncio
    async def test_collection_default_not_public(self, db_session):
        """New collection should have is_public=False by default."""
        user = User(username="col_pub", email="cp@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        col = Collection(name="Priv Col", owner_id=user.id)
        db_session.add(col)
        await db_session.commit()
        await db_session.refresh(col)
        assert col.is_public is False


# ============================================================================
# DOCUMENT MODEL
# ============================================================================

class TestDocumentModel:
    """Verify Document ORM model behavior."""

    async def _make_user_and_col(self, db_session, prefix="dm"):
        user = User(username=f"{prefix}_u", email=f"{prefix}@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        col = Collection(name=f"{prefix} Col", owner_id=user.id)
        db_session.add(col)
        await db_session.flush()
        return user, col

    @pytest.mark.asyncio
    async def test_create_document(self, db_session):
        """Should create document with filename, file_type, visibility, owner_id."""
        user, col = await self._make_user_and_col(db_session, "cd")
        doc = Document(filename="report.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        assert doc.filename == "report.pdf"

    @pytest.mark.asyncio
    async def test_document_id_is_uuid(self, db_session):
        """Document.id should be auto-generated UUID."""
        user, col = await self._make_user_and_col(db_session, "du")
        doc = Document(filename="u.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        parsed = uuid_mod.UUID(doc.id)
        assert str(parsed) == doc.id

    @pytest.mark.asyncio
    async def test_document_default_status_pending(self, db_session):
        """New document should have status='pending'."""
        user, col = await self._make_user_and_col(db_session, "ds")
        doc = Document(filename="s.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        assert doc.status == DocumentStatusEnum.PENDING.value

    @pytest.mark.asyncio
    async def test_document_visibility_public(self, db_session):
        """Document with visibility='public' should be valid."""
        user, col = await self._make_user_and_col(db_session, "vp")
        doc = Document(
            filename="p.pdf", file_type="pdf", owner_id=user.id,
            collection_id=col.id, visibility=VisibilityEnum.PUBLIC.value,
        )
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        assert doc.visibility == "public"

    @pytest.mark.asyncio
    async def test_document_visibility_team(self, db_session):
        """Document with visibility='team' should be valid."""
        user, col = await self._make_user_and_col(db_session, "vt")
        doc = Document(
            filename="t.pdf", file_type="pdf", owner_id=user.id,
            collection_id=col.id, visibility=VisibilityEnum.TEAM.value,
        )
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        assert doc.visibility == "team"

    @pytest.mark.asyncio
    async def test_document_visibility_confidential(self, db_session):
        """Document with visibility='confidential' should be valid."""
        user, col = await self._make_user_and_col(db_session, "vc")
        doc = Document(
            filename="c.pdf", file_type="pdf", owner_id=user.id,
            collection_id=col.id, visibility=VisibilityEnum.CONFIDENTIAL.value,
        )
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        assert doc.visibility == "confidential"

    @pytest.mark.asyncio
    async def test_document_invalid_visibility_raises(self, db_session):
        """Document with visibility='unknown' should raise on commit."""
        user, col = await self._make_user_and_col(db_session, "vi")
        doc = Document(
            filename="i.pdf", file_type="pdf", owner_id=user.id,
            collection_id=col.id, visibility="unknown",
        )
        db_session.add(doc)
        with pytest.raises(Exception):  # StatementError wrapping ValueError
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_document_owner_relationship(self, db_session):
        """document.owner should return the User who uploaded it."""
        user, col = await self._make_user_and_col(db_session, "do")
        doc = Document(filename="o.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        assert doc.owner.username == "do_u"

    @pytest.mark.asyncio
    async def test_document_collection_relationship(self, db_session):
        """document.collection should return the parent Collection."""
        user, col = await self._make_user_and_col(db_session, "dcr")
        doc = Document(filename="cr.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        assert doc.collection.name == "dcr Col"

    @pytest.mark.asyncio
    async def test_document_created_at_auto_set(self, db_session):
        """created_at should be auto-populated."""
        user, col = await self._make_user_and_col(db_session, "dca")
        doc = Document(filename="ca.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.commit()
        await db_session.refresh(doc)
        assert doc.created_at is not None


# ============================================================================
# DOCUMENT TEAM ACCESS
# ============================================================================

class TestDocumentTeamAccess:
    """Verify Document <-> Team access control junction."""

    async def _setup(self, db_session, prefix="dta"):
        user = User(username=f"{prefix}_u", email=f"{prefix}@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name=f"{prefix} Team", created_by=user.id)
        col = Collection(name=f"{prefix} Col", owner_id=user.id)
        db_session.add_all([team, col])
        await db_session.flush()
        doc = Document(filename=f"{prefix}.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.flush()
        return user, team, col, doc

    @pytest.mark.asyncio
    async def test_assign_team_to_document(self, db_session):
        """Should link a team/DL to a document."""
        _, team, _, doc = await self._setup(db_session, "at")
        dta = DocumentTeamAccess(document_id=doc.id, team_id=team.id)
        db_session.add(dta)
        await db_session.commit()
        await db_session.refresh(doc)
        assert len(doc.team_access) == 1

    @pytest.mark.asyncio
    async def test_document_can_have_multiple_teams(self, db_session):
        """A document can be shared with multiple DLs."""
        user, team1, col, doc = await self._setup(db_session, "mt")
        team2 = Team(name="mt Team 2", created_by=user.id)
        db_session.add(team2)
        await db_session.flush()
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team1.id))
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team2.id))
        await db_session.commit()
        await db_session.refresh(doc)
        assert len(doc.team_access) == 2

    @pytest.mark.asyncio
    async def test_team_can_access_multiple_documents(self, db_session):
        """A DL can be assigned to multiple documents."""
        user, team, col, doc1 = await self._setup(db_session, "md")
        doc2 = Document(filename="md2.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc2)
        await db_session.flush()
        db_session.add(DocumentTeamAccess(document_id=doc1.id, team_id=team.id))
        db_session.add(DocumentTeamAccess(document_id=doc2.id, team_id=team.id))
        await db_session.commit()
        await db_session.refresh(team)
        assert len(team.documents) == 2

    @pytest.mark.asyncio
    async def test_remove_team_access(self, db_session):
        """Removing a DocumentTeamAccess row should revoke team access."""
        _, team, _, doc = await self._setup(db_session, "rm")
        dta = DocumentTeamAccess(document_id=doc.id, team_id=team.id)
        db_session.add(dta)
        await db_session.commit()
        await db_session.delete(dta)
        await db_session.commit()
        await db_session.refresh(doc)
        assert len(doc.team_access) == 0

    @pytest.mark.asyncio
    async def test_delete_document_cascades_team_access(self, db_session):
        """Deleting a document should remove all its DocumentTeamAccess rows."""
        _, team, _, doc = await self._setup(db_session, "dc")
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
        await db_session.commit()
        doc_id = doc.id
        await db_session.delete(doc)
        await db_session.commit()
        result = await db_session.execute(
            select(DocumentTeamAccess).where(DocumentTeamAccess.document_id == doc_id)
        )
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_duplicate_team_access_raises(self, db_session):
        """Same team assigned to same document twice should raise IntegrityError."""
        _, team, _, doc = await self._setup(db_session, "dup")
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
        await db_session.commit()
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
        with pytest.raises(IntegrityError):
            await db_session.commit()


# ============================================================================
# DOCUMENT USER ACCESS
# ============================================================================

class TestDocumentUserAccess:
    """Verify Document <-> User explicit access (for confidential docs)."""

    async def _setup(self, db_session, prefix="dua"):
        user = User(username=f"{prefix}_u", email=f"{prefix}@b.com", hashed_password="h")
        other = User(username=f"{prefix}_o", email=f"{prefix}_o@b.com", hashed_password="h")
        db_session.add_all([user, other])
        await db_session.flush()
        col = Collection(name=f"{prefix} Col", owner_id=user.id)
        db_session.add(col)
        await db_session.flush()
        doc = Document(
            filename=f"{prefix}.pdf", file_type="pdf", owner_id=user.id,
            collection_id=col.id, visibility="confidential",
        )
        db_session.add(doc)
        await db_session.flush()
        return user, other, col, doc

    @pytest.mark.asyncio
    async def test_grant_user_access_to_document(self, db_session):
        """Should link a user to a confidential document."""
        _, other, _, doc = await self._setup(db_session, "ga")
        dua = DocumentUserAccess(document_id=doc.id, user_id=other.id)
        db_session.add(dua)
        await db_session.commit()
        await db_session.refresh(doc)
        assert len(doc.user_access) == 1

    @pytest.mark.asyncio
    async def test_document_can_have_multiple_allowed_users(self, db_session):
        """A confidential document can have multiple explicit users."""
        user, other, _, doc = await self._setup(db_session, "mu")
        u3 = User(username="mu_u3", email="mu_u3@b.com", hashed_password="h")
        db_session.add(u3)
        await db_session.flush()
        db_session.add(DocumentUserAccess(document_id=doc.id, user_id=other.id))
        db_session.add(DocumentUserAccess(document_id=doc.id, user_id=u3.id))
        await db_session.commit()
        await db_session.refresh(doc)
        assert len(doc.user_access) == 2

    @pytest.mark.asyncio
    async def test_remove_user_access(self, db_session):
        """Removing DocumentUserAccess should revoke that user's access."""
        _, other, _, doc = await self._setup(db_session, "rua")
        dua = DocumentUserAccess(document_id=doc.id, user_id=other.id)
        db_session.add(dua)
        await db_session.commit()
        await db_session.delete(dua)
        await db_session.commit()
        await db_session.refresh(doc)
        assert len(doc.user_access) == 0

    @pytest.mark.asyncio
    async def test_delete_document_cascades_user_access(self, db_session):
        """Deleting a document should remove all its DocumentUserAccess rows."""
        _, other, _, doc = await self._setup(db_session, "dcua")
        db_session.add(DocumentUserAccess(document_id=doc.id, user_id=other.id))
        await db_session.commit()
        doc_id = doc.id
        await db_session.delete(doc)
        await db_session.commit()
        result = await db_session.execute(
            select(DocumentUserAccess).where(DocumentUserAccess.document_id == doc_id)
        )
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_duplicate_user_access_raises(self, db_session):
        """Same user granted access twice should raise IntegrityError."""
        _, other, _, doc = await self._setup(db_session, "dupua")
        db_session.add(DocumentUserAccess(document_id=doc.id, user_id=other.id))
        await db_session.commit()
        db_session.add(DocumentUserAccess(document_id=doc.id, user_id=other.id))
        with pytest.raises(IntegrityError):
            await db_session.commit()
