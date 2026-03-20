"""
TDD Test Cases — Audit Repository (src/repositories/audit_repository.py)
"""
import pytest

from sqlalchemy import select

from src.models.user import User
from src.models.team import Team
from src.models.document import Collection, Document
from src.models.audit import DocumentAuditLog, TeamAuditLog


# ---------------------------------------------------------------------------
# Helpers — create minimal DB records required by FK constraints
# ---------------------------------------------------------------------------

async def _make_user(db_session, username: str, email: str) -> User:
    u = User(username=username, email=email, hashed_password="h")
    db_session.add(u)
    await db_session.flush()
    return u


async def _make_document(db_session, user: User, filename: str = "audit_doc.pdf") -> Document:
    col = Collection(name=f"Audit Col {filename}", owner_id=user.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(filename=filename, file_type="pdf", owner_id=user.id, collection_id=col.id)
    db_session.add(doc)
    await db_session.flush()
    return doc


async def _make_team(db_session, user: User, name: str = "Audit Team") -> Team:
    t = Team(name=name, created_by=user.id)
    db_session.add(t)
    await db_session.flush()
    return t


class TestDocumentAuditLog:
    """Verify document change audit trail."""

    async def test_log_document_creation(self, audit_repo, db_session):
        """Should log action='created' with document metadata."""
        user = await _make_user(db_session, "doc_log_creator", "doc_log_creator@test.com")
        doc = await _make_document(db_session, user, "created_audit.pdf")

        await audit_repo.log_document_change(
            document_id=doc.id,
            user_id=user.id,
            action="created",
            new_metadata={"filename": "created_audit.pdf"},
        )

        result = await db_session.execute(
            select(DocumentAuditLog).where(DocumentAuditLog.document_id == doc.id)
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].action == "created"
        assert logs[0].document_id == doc.id

    async def test_log_visibility_change(self, audit_repo, db_session):
        """Should log action='visibility_changed' with old and new metadata."""
        user = await _make_user(db_session, "vis_change_user", "vis_change@test.com")
        doc = await _make_document(db_session, user, "vis_change.pdf")

        await audit_repo.log_document_change(
            document_id=doc.id,
            user_id=user.id,
            action="visibility_changed",
            old_metadata={"visibility": "public"},
            new_metadata={"visibility": "confidential"},
        )

        result = await db_session.execute(
            select(DocumentAuditLog).where(DocumentAuditLog.document_id == doc.id)
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].action == "visibility_changed"
        assert logs[0].old_metadata == {"visibility": "public"}
        assert logs[0].new_metadata == {"visibility": "confidential"}

    async def test_log_ownership_transfer(self, audit_repo, db_session):
        """Should log action='ownership_transferred' with old and new owner."""
        user = await _make_user(db_session, "old_owner_audit", "old_owner_audit@test.com")
        new_owner = await _make_user(db_session, "new_owner_audit", "new_owner_audit@test.com")
        doc = await _make_document(db_session, user, "transfer_audit.pdf")

        await audit_repo.log_document_change(
            document_id=doc.id,
            user_id=user.id,
            action="ownership_transferred",
            old_metadata={"owner_id": user.id},
            new_metadata={"owner_id": new_owner.id},
        )

        result = await db_session.execute(
            select(DocumentAuditLog).where(DocumentAuditLog.document_id == doc.id)
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].action == "ownership_transferred"
        assert logs[0].new_metadata["owner_id"] == new_owner.id

    async def test_log_document_deletion(self, audit_repo, db_session):
        """Should log action='deleted' with document metadata snapshot."""
        user = await _make_user(db_session, "del_audit_user", "del_audit@test.com")
        doc = await _make_document(db_session, user, "deleted_audit.pdf")

        await audit_repo.log_document_change(
            document_id=doc.id,
            user_id=user.id,
            action="deleted",
            old_metadata={"filename": "deleted_audit.pdf", "status": "ready"},
        )

        result = await db_session.execute(
            select(DocumentAuditLog).where(DocumentAuditLog.document_id == doc.id)
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].action == "deleted"
        assert logs[0].old_metadata is not None

    async def test_audit_log_has_timestamp(self, audit_repo, db_session):
        """created_at should be auto-populated."""
        user = await _make_user(db_session, "ts_audit_user", "ts_audit@test.com")
        doc = await _make_document(db_session, user, "ts_audit.pdf")

        await audit_repo.log_document_change(
            document_id=doc.id,
            user_id=user.id,
            action="created",
        )

        result = await db_session.execute(
            select(DocumentAuditLog).where(DocumentAuditLog.document_id == doc.id)
        )
        log = result.scalar_one()

        assert log.created_at is not None

    async def test_audit_log_has_user_id(self, audit_repo, db_session):
        """user_id should record who made the change."""
        user = await _make_user(db_session, "uid_audit_user", "uid_audit@test.com")
        doc = await _make_document(db_session, user, "uid_audit.pdf")

        await audit_repo.log_document_change(
            document_id=doc.id,
            user_id=user.id,
            action="created",
        )

        result = await db_session.execute(
            select(DocumentAuditLog).where(DocumentAuditLog.document_id == doc.id)
        )
        log = result.scalar_one()

        assert log.user_id == user.id


class TestTeamAuditLog:
    """Verify team change audit trail."""

    async def test_log_team_creation(self, audit_repo, db_session):
        user = await _make_user(db_session, "team_create_auditor", "team_create_audit@test.com")
        team = await _make_team(db_session, user, "Created Audit Team")

        await audit_repo.log_team_change(
            team_id=team.id,
            user_id=user.id,
            action="created",
        )

        result = await db_session.execute(
            select(TeamAuditLog).where(TeamAuditLog.team_id == team.id)
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].action == "created"
        assert logs[0].team_id == team.id
        assert logs[0].user_id == user.id

    async def test_log_member_added(self, audit_repo, db_session):
        """Should include target_user_id."""
        actor = await _make_user(db_session, "mem_add_actor", "mem_add_actor@test.com")
        target = await _make_user(db_session, "mem_add_target", "mem_add_target@test.com")
        team = await _make_team(db_session, actor, "Member Add Audit Team")

        await audit_repo.log_team_change(
            team_id=team.id,
            user_id=actor.id,
            action="member_added",
            member_id=target.id,
        )

        result = await db_session.execute(
            select(TeamAuditLog).where(TeamAuditLog.team_id == team.id)
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].action == "member_added"
        assert logs[0].target_user_id == target.id

    async def test_log_member_removed(self, audit_repo, db_session):
        actor = await _make_user(db_session, "mem_rm_actor", "mem_rm_actor@test.com")
        target = await _make_user(db_session, "mem_rm_target", "mem_rm_target@test.com")
        team = await _make_team(db_session, actor, "Member Remove Audit Team")

        await audit_repo.log_team_change(
            team_id=team.id,
            user_id=actor.id,
            action="member_removed",
            member_id=target.id,
        )

        result = await db_session.execute(
            select(TeamAuditLog).where(TeamAuditLog.team_id == team.id)
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].action == "member_removed"
        assert logs[0].target_user_id == target.id

    async def test_log_team_deleted(self, audit_repo, db_session):
        user = await _make_user(db_session, "team_del_auditor", "team_del_audit@test.com")
        team = await _make_team(db_session, user, "Deleted Audit Team")

        await audit_repo.log_team_change(
            team_id=team.id,
            user_id=user.id,
            action="deleted",
        )

        result = await db_session.execute(
            select(TeamAuditLog).where(TeamAuditLog.team_id == team.id)
        )
        logs = result.scalars().all()

        assert len(logs) == 1
        assert logs[0].action == "deleted"
        assert logs[0].team_id == team.id
