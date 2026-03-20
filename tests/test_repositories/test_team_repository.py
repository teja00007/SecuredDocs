"""
TDD Test Cases — Team Repository (src/repositories/team_repository.py)
"""
import pytest

from src.models.user import User
from src.models.team import Team, TeamMembership


class TestTeamRepositoryGetDocumentsOnlyInTeam:
    """Critical query for team deletion orphan handling (Fix #1)."""

    async def test_returns_docs_only_in_this_team(self, team_repo, db_session, team, single_team_docs):
        """Documents with visibility='team' whose only assigned team is this one."""
        docs = await team_repo.get_documents_only_in_team(team.id)

        assert len(docs) >= 1
        doc_ids = [d.id for d in docs]
        for doc in single_team_docs:
            assert doc.id in doc_ids

    async def test_excludes_multi_team_docs(self, team_repo, db_session, team, multi_team_docs):
        """Documents assigned to [team, other_team] should NOT be returned."""
        docs = await team_repo.get_documents_only_in_team(team.id)

        doc_ids = [d.id for d in docs]
        for doc in multi_team_docs:
            assert doc.id not in doc_ids

    async def test_excludes_non_team_visibility_docs(self, team_repo, db_session, team, public_docs):
        """Public/confidential docs should not be returned even if team has access."""
        docs = await team_repo.get_documents_only_in_team(team.id)

        doc_ids = [d.id for d in docs]
        for doc in public_docs:
            assert doc.id not in doc_ids

    async def test_returns_empty_if_no_orphans(self, team_repo, db_session, team):
        """If all docs have multiple teams, return empty list."""
        # No single_team_docs fixture — team has no exclusively-assigned docs
        docs = await team_repo.get_documents_only_in_team(team.id)

        assert docs == []


class TestTeamRepositoryCRUD:
    """Basic team CRUD operations."""

    async def test_create_team(self, team_repo, db_session):
        creator = User(username="crud_creator", email="crud_creator@test.com", hashed_password="h")
        db_session.add(creator)
        await db_session.flush()

        team = Team(name="New CRUD Team", created_by=creator.id)
        created = await team_repo.create(team)

        assert created.id is not None
        assert created.id != ""
        assert created.name == "New CRUD Team"

    async def test_get_by_id(self, team_repo, db_session, saved_team):
        fetched = await team_repo.get_by_id(saved_team.id)

        assert fetched is not None
        assert fetched.id == saved_team.id
        assert fetched.name == saved_team.name

    async def test_get_by_name(self, team_repo, db_session, saved_team):
        fetched = await team_repo.get_by_name(saved_team.name)

        assert fetched is not None
        assert fetched.id == saved_team.id
        assert fetched.name == saved_team.name

    async def test_list_for_user(self, team_repo, db_session, user_with_teams):
        teams = await team_repo.list_for_user(user_with_teams.id)

        assert len(teams) >= 2
        # user_with_teams is creator and member of Alpha Team and Beta Team
        team_names = {t.name for t in teams}
        assert "Alpha Team" in team_names
        assert "Beta Team" in team_names

    async def test_add_member(self, team_repo, db_session, saved_team, new_user):
        await team_repo.add_member(saved_team.id, new_user.id)

        members = await team_repo.get_members(saved_team.id)
        member_ids = [m.id for m in members]
        assert new_user.id in member_ids

    async def test_remove_member(self, team_repo, db_session, saved_team, member):
        # Verify member is present before removal
        members_before = await team_repo.get_members(saved_team.id)
        assert any(m.id == member.id for m in members_before)

        await team_repo.remove_member(saved_team.id, member.id)

        members_after = await team_repo.get_members(saved_team.id)
        member_ids_after = [m.id for m in members_after]
        assert member.id not in member_ids_after

    async def test_get_members(self, team_repo, db_session, saved_team, member):
        members = await team_repo.get_members(saved_team.id)

        assert len(members) >= 1
        member_ids = [m.id for m in members]
        assert member.id in member_ids
