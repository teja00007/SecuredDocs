"""
TDD Test Cases — Team Service (src/services/team_service.py)

Tests for team lifecycle, especially the critical team-deletion-orphan handling.
"""
import pytest

from src.models import Team, TeamMembership, Document, DocumentTeamAccess
from src.core.rbac import UserContext
from src.core.exceptions import TeamNotFoundError, AuthorizationError


# ============================================================================
# TEAM DELETION — ORPHANED DOCUMENT HANDLING (Critical Fix #1)
# ============================================================================

class TestTeamDeletion:
    """team_service.delete_team() — must handle orphaned documents."""

    async def test_delete_team_reverts_orphaned_docs_to_confidential(self, team_service, db_session, registered_user):
        team = Team(name="SoloTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.flush()
        doc = Document(filename="orphan.pdf", file_type="application/pdf",
                       visibility="team", status="ready", owner_id=registered_user.id)
        db_session.add(doc)
        await db_session.flush()
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
        await db_session.commit()
        await db_session.refresh(doc)

        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.delete_team(team.id, ctx)
        await db_session.refresh(doc)
        assert doc.visibility == "confidential"

    async def test_delete_team_does_not_revert_multi_dl_docs(self, team_service, db_session, registered_user):
        team_a = Team(name="TeamA", description="", created_by=registered_user.id)
        team_b = Team(name="TeamB", description="", created_by=registered_user.id)
        db_session.add_all([team_a, team_b])
        await db_session.flush()
        doc = Document(filename="multi.pdf", file_type="application/pdf",
                       visibility="team", status="ready", owner_id=registered_user.id)
        db_session.add(doc)
        await db_session.flush()
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team_a.id))
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team_b.id))
        await db_session.commit()
        await db_session.refresh(doc)

        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.delete_team(team_a.id, ctx)
        await db_session.refresh(doc)
        assert doc.visibility == "team"

    async def test_delete_team_updates_vector_store_metadata(self, team_service, mock_vector_store, db_session, registered_user):
        team = Team(name="VSTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.flush()
        doc = Document(filename="vs.pdf", file_type="application/pdf",
                       visibility="team", status="ready", owner_id=registered_user.id)
        db_session.add(doc)
        await db_session.flush()
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
        await db_session.commit()

        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.delete_team(team.id, ctx)
        mock_vector_store.update_metadata.assert_called()

    async def test_delete_team_logs_audit_trail(self, team_service, db_session, registered_user):
        from sqlalchemy import select
        from src.models.audit import TeamAuditLog
        team = Team(name="AuditTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.commit()

        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.delete_team(team.id, ctx)
        logs = (await db_session.execute(select(TeamAuditLog))).scalars().all()
        assert any(log.action == "deleted" for log in logs)

    async def test_delete_team_removes_memberships(self, team_service, db_session, registered_user):
        from sqlalchemy import select
        team = Team(name="MemberTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.flush()
        db_session.add(TeamMembership(team_id=team.id, user_id=registered_user.id))
        await db_session.commit()

        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.delete_team(team.id, ctx)
        memberships = (await db_session.execute(
            select(TeamMembership).where(TeamMembership.team_id == team.id)
        )).scalars().all()
        assert len(memberships) == 0

    async def test_delete_team_removes_document_team_access(self, team_service, db_session, registered_user):
        from sqlalchemy import select
        team = Team(name="AccessTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.flush()
        doc = Document(filename="access.pdf", file_type="application/pdf",
                       visibility="team", status="ready", owner_id=registered_user.id)
        db_session.add(doc)
        await db_session.flush()
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
        await db_session.commit()

        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.delete_team(team.id, ctx)
        accesses = (await db_session.execute(
            select(DocumentTeamAccess).where(DocumentTeamAccess.team_id == team.id)
        )).scalars().all()
        assert len(accesses) == 0

    async def test_delete_team_does_not_delete_documents(self, team_service, db_session, registered_user):
        from sqlalchemy import select
        team = Team(name="NoDelDocTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.flush()
        doc = Document(filename="nodeldoc.pdf", file_type="application/pdf",
                       visibility="team", status="ready", owner_id=registered_user.id)
        db_session.add(doc)
        await db_session.flush()
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
        await db_session.commit()
        doc_id = doc.id

        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.delete_team(team.id, ctx)
        doc_after = (await db_session.execute(
            select(Document).where(Document.id == doc_id)
        )).scalar_one_or_none()
        assert doc_after is not None

    async def test_delete_team_only_creator_or_admin(self, team_service, non_creator_user, db_session, registered_user):
        team = Team(name="CreatorTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.commit()

        ctx = UserContext(user_id=non_creator_user.id, roles=[], team_ids=[])
        with pytest.raises(AuthorizationError):
            await team_service.delete_team(team.id, ctx)

    async def test_delete_nonexistent_team_raises(self, team_service, registered_user):
        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        with pytest.raises(TeamNotFoundError):
            await team_service.delete_team("nonexistent-team-id", ctx)


class TestTeamCreate:
    """team_service.create_team()"""

    @pytest.mark.xfail(strict=False, reason="TeamService.create_team() not implemented")
    async def test_create_team_adds_creator_as_member(self, team_service, db_session, registered_user):
        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        team = await team_service.create_team("NewTeam", "desc", ctx)
        from sqlalchemy import select
        membership = (await db_session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == registered_user.id,
            )
        )).scalar_one_or_none()
        assert membership is not None

    @pytest.mark.xfail(strict=False, reason="TeamService.create_team() not implemented")
    async def test_create_team_logs_audit(self, team_service, db_session, registered_user):
        from sqlalchemy import select
        from src.models.audit import TeamAuditLog
        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.create_team("LoggedTeam", "desc", ctx)
        logs = (await db_session.execute(select(TeamAuditLog))).scalars().all()
        assert any(log.action == "created" for log in logs)

    @pytest.mark.xfail(strict=False, reason="TeamService.create_team() not implemented")
    async def test_create_team_with_members_logs_each(self, team_service, db_session, registered_user, non_creator_user):
        from sqlalchemy import select
        from src.models.audit import TeamAuditLog
        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.create_team("MemberTeam", "desc", ctx,
                                       member_ids=[non_creator_user.id])
        logs = (await db_session.execute(select(TeamAuditLog))).scalars().all()
        assert any(log.action == "member_added" for log in logs)


class TestTeamMembershipChanges:
    """team_service add/remove member operations."""

    @pytest.mark.xfail(strict=False, reason="TeamService.add_member() not implemented")
    async def test_add_member_logs_audit(self, team_service, db_session, registered_user, non_creator_user):
        from sqlalchemy import select
        from src.models.audit import TeamAuditLog
        team = Team(name="AddMemberTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.commit()
        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.add_member(team.id, non_creator_user.id, ctx)
        logs = (await db_session.execute(select(TeamAuditLog))).scalars().all()
        assert any(log.action == "member_added" for log in logs)

    @pytest.mark.xfail(strict=False, reason="TeamService.remove_member() not implemented")
    async def test_remove_member_logs_audit(self, team_service, db_session, registered_user, non_creator_user):
        from sqlalchemy import select
        from src.models.audit import TeamAuditLog
        team = Team(name="RemMemberTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.flush()
        db_session.add(TeamMembership(team_id=team.id, user_id=non_creator_user.id))
        await db_session.commit()
        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.remove_member(team.id, non_creator_user.id, ctx)
        logs = (await db_session.execute(select(TeamAuditLog))).scalars().all()
        assert any(log.action == "member_removed" for log in logs)

    @pytest.mark.xfail(strict=False, reason="TeamService.remove_member() not implemented")
    async def test_remove_member_does_not_affect_documents(self, team_service, db_session, registered_user, non_creator_user):
        from sqlalchemy import select
        team = Team(name="DocIntactTeam", description="", created_by=registered_user.id)
        db_session.add(team)
        await db_session.flush()
        doc = Document(filename="intact.pdf", file_type="application/pdf",
                       visibility="team", status="ready", owner_id=registered_user.id)
        db_session.add(doc)
        await db_session.flush()
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
        db_session.add(TeamMembership(team_id=team.id, user_id=non_creator_user.id))
        await db_session.commit()

        ctx = UserContext(user_id=registered_user.id, roles=[], team_ids=[])
        await team_service.remove_member(team.id, non_creator_user.id, ctx)
        accesses = (await db_session.execute(
            select(DocumentTeamAccess).where(DocumentTeamAccess.team_id == team.id)
        )).scalars().all()
        assert len(accesses) >= 1
