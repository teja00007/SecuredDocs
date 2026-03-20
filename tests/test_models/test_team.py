"""
TDD Test Cases — Team/DL Models (src/models/team.py)

Tests for Team (Distribution List) and TeamMembership ORM models.
"""
import pytest
import uuid as uuid_mod

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.user import User
from src.models.team import Team, TeamMembership
from src.models.document import Document, DocumentTeamAccess, Collection
from src.core.security import hash_password


# ============================================================================
# TEAM MODEL
# ============================================================================

class TestTeamModel:
    """Verify Team (Distribution List) ORM model behavior."""

    @pytest.mark.asyncio
    async def test_create_team(self, db_session):
        """Should create team with name, description, created_by."""
        user = User(username="creator", email="c@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="Alpha Team", description="First team", created_by=user.id)
        db_session.add(team)
        await db_session.commit()
        await db_session.refresh(team)
        assert team.name == "Alpha Team"
        assert team.description == "First team"

    @pytest.mark.asyncio
    async def test_team_id_is_uuid(self, db_session):
        """Team.id should be auto-generated UUID."""
        user = User(username="tc", email="tc@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="UUID Team", created_by=user.id)
        db_session.add(team)
        await db_session.commit()
        await db_session.refresh(team)
        parsed = uuid_mod.UUID(team.id)
        assert str(parsed) == team.id

    @pytest.mark.xfail(reason="Team names are intentionally not globally unique — uniqueness is per-company in multi-tenant mode")
    @pytest.mark.asyncio
    async def test_team_name_is_unique(self, db_session):
        """Duplicate team name should raise IntegrityError."""
        user = User(username="tu", email="tu@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        t1 = Team(name="DupTeam", created_by=user.id)
        t2 = Team(name="DupTeam", created_by=user.id)
        db_session.add(t1)
        await db_session.commit()
        db_session.add(t2)
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_team_created_at_auto_set(self, db_session):
        """created_at should be auto-populated."""
        user = User(username="tca", email="tca@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="TS Team", created_by=user.id)
        db_session.add(team)
        await db_session.commit()
        await db_session.refresh(team)
        assert team.created_at is not None

    @pytest.mark.asyncio
    async def test_team_creator_relationship(self, db_session):
        """team.creator should return the User who created it."""
        user = User(username="tcr", email="tcr@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="Creator Team", created_by=user.id)
        db_session.add(team)
        await db_session.commit()
        await db_session.refresh(team)
        assert team.creator.username == "tcr"

    @pytest.mark.asyncio
    async def test_team_members_relationship(self, db_session):
        """team.members should return list of User objects."""
        user = User(username="tmr", email="tmr@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="Members Team", created_by=user.id)
        db_session.add(team)
        await db_session.flush()
        m = TeamMembership(team_id=team.id, user_id=user.id)
        db_session.add(m)
        await db_session.commit()
        await db_session.refresh(team)
        assert len(team.members) == 1
        assert team.members[0].username == "tmr"

    @pytest.mark.asyncio
    async def test_team_documents_relationship(self, db_session):
        """team.documents should return list of Documents accessible via this DL."""
        user = User(username="tdr", email="tdr@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="Doc Team", created_by=user.id)
        col = Collection(name="DocCol", owner_id=user.id)
        db_session.add(team)
        db_session.add(col)
        await db_session.flush()
        doc = Document(filename="test.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.flush()
        dta = DocumentTeamAccess(document_id=doc.id, team_id=team.id)
        db_session.add(dta)
        await db_session.commit()
        await db_session.refresh(team)
        assert len(team.documents) == 1
        assert team.documents[0].filename == "test.pdf"


# ============================================================================
# TEAM MEMBERSHIP
# ============================================================================

class TestTeamMembership:
    """Verify many-to-many Team <-> User relationship."""

    @pytest.mark.asyncio
    async def test_add_member_to_team(self, db_session):
        """Adding user to team.members should persist."""
        user = User(username="am1", email="am1@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="Add Team", created_by=user.id)
        db_session.add(team)
        await db_session.flush()
        m = TeamMembership(team_id=team.id, user_id=user.id)
        db_session.add(m)
        await db_session.commit()
        await db_session.refresh(team)
        assert len(team.members) == 1

    @pytest.mark.asyncio
    async def test_team_can_have_multiple_members(self, db_session):
        """A team should support multiple users."""
        u1 = User(username="mm1", email="mm1@b.com", hashed_password="h")
        u2 = User(username="mm2", email="mm2@b.com", hashed_password="h")
        db_session.add_all([u1, u2])
        await db_session.flush()
        team = Team(name="Multi Team", created_by=u1.id)
        db_session.add(team)
        await db_session.flush()
        db_session.add(TeamMembership(team_id=team.id, user_id=u1.id))
        db_session.add(TeamMembership(team_id=team.id, user_id=u2.id))
        await db_session.commit()
        await db_session.refresh(team)
        assert len(team.members) == 2

    @pytest.mark.asyncio
    async def test_user_can_be_in_multiple_teams(self, db_session):
        """A user should belong to multiple DLs."""
        user = User(username="mt1", email="mt1@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        t1 = Team(name="Team A", created_by=user.id)
        t2 = Team(name="Team B", created_by=user.id)
        db_session.add_all([t1, t2])
        await db_session.flush()
        db_session.add(TeamMembership(team_id=t1.id, user_id=user.id))
        db_session.add(TeamMembership(team_id=t2.id, user_id=user.id))
        await db_session.commit()
        await db_session.refresh(user)
        assert len(user.teams) == 2

    @pytest.mark.asyncio
    async def test_remove_member_from_team(self, db_session):
        """Removing user from team.members should persist."""
        user = User(username="rm1", email="rm1@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="Remove Team", created_by=user.id)
        db_session.add(team)
        await db_session.flush()
        m = TeamMembership(team_id=team.id, user_id=user.id)
        db_session.add(m)
        await db_session.commit()
        await db_session.refresh(team)
        assert len(team.members) == 1

        await db_session.delete(m)
        await db_session.commit()
        await db_session.refresh(team)
        assert len(team.members) == 0

    @pytest.mark.asyncio
    async def test_duplicate_membership_raises(self, db_session):
        """Adding same user twice should raise IntegrityError."""
        user = User(username="dm1", email="dm1@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="Dup Mem Team", created_by=user.id)
        db_session.add(team)
        await db_session.flush()
        db_session.add(TeamMembership(team_id=team.id, user_id=user.id))
        await db_session.commit()
        db_session.add(TeamMembership(team_id=team.id, user_id=user.id))
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_delete_team_cascades_memberships(self, db_session):
        """Deleting a team should remove all TeamMembership rows."""
        user = User(username="dc1", email="dc1@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="Cascade Team", created_by=user.id)
        db_session.add(team)
        await db_session.flush()
        db_session.add(TeamMembership(team_id=team.id, user_id=user.id))
        await db_session.commit()

        await db_session.delete(team)
        await db_session.commit()
        result = await db_session.execute(
            select(TeamMembership).where(TeamMembership.team_id == team.id)
        )
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_delete_team_cascades_document_team_access(self, db_session):
        """Deleting a team should remove all DocumentTeamAccess rows for that team."""
        user = User(username="dtc", email="dtc@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="DTA Team", created_by=user.id)
        col = Collection(name="DTA Col", owner_id=user.id)
        db_session.add_all([team, col])
        await db_session.flush()
        doc = Document(filename="dta.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
        db_session.add(doc)
        await db_session.flush()
        dta = DocumentTeamAccess(document_id=doc.id, team_id=team.id)
        db_session.add(dta)
        await db_session.commit()

        await db_session.delete(team)
        await db_session.commit()
        result = await db_session.execute(
            select(DocumentTeamAccess).where(DocumentTeamAccess.team_id == team.id)
        )
        assert result.scalars().all() == []

    @pytest.mark.asyncio
    async def test_delete_user_cascades_memberships(self, db_session):
        """Deleting a user should remove their TeamMembership rows."""
        creator = User(username="duc_c", email="duc_c@b.com", hashed_password="h")
        member = User(username="duc_m", email="duc_m@b.com", hashed_password="h")
        db_session.add_all([creator, member])
        await db_session.flush()
        team = Team(name="UserCascade Team", created_by=creator.id)
        db_session.add(team)
        await db_session.flush()
        db_session.add(TeamMembership(team_id=team.id, user_id=member.id))
        await db_session.commit()

        await db_session.delete(member)
        await db_session.commit()
        result = await db_session.execute(
            select(TeamMembership).where(TeamMembership.user_id == member.id)
        )
        assert result.scalars().all() == []
