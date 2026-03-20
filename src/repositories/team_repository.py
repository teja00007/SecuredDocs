"""Team data access layer."""

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.team import Team, TeamMembership
from src.models.user import User
from src.models.document import Document, DocumentTeamAccess


class TeamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, team_id: str) -> Team | None:
        result = await self._session.execute(select(Team).where(Team.id == team_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Team | None:
        result = await self._session.execute(select(Team).where(Team.name == name))
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str, company_id: str | None = None) -> list[Team]:
        stmt = select(Team).where(
            (Team.created_by == user_id) |
            Team.id.in_(
                select(TeamMembership.team_id).where(TeamMembership.user_id == user_id)
            )
        )
        if company_id:
            stmt = stmt.where(Team.company_id == company_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_all(self, skip: int = 0, limit: int = 50) -> list[Team]:
        result = await self._session.execute(select(Team).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def create(self, team: Team) -> Team:
        self._session.add(team)
        await self._session.flush()
        await self._session.refresh(team)
        return team

    async def update(self, team: Team) -> Team:
        self._session.add(team)
        await self._session.flush()
        await self._session.refresh(team)
        return team

    async def delete(self, team_id: str) -> None:
        team = await self.get_by_id(team_id)
        if team:
            await self._session.delete(team)
            await self._session.flush()

    async def add_member(self, team_id: str, user_id: str) -> None:
        existing = await self._session.execute(
            select(TeamMembership).where(
                and_(TeamMembership.team_id == team_id, TeamMembership.user_id == user_id)
            )
        )
        if not existing.scalar_one_or_none():
            membership = TeamMembership(team_id=team_id, user_id=user_id)
            self._session.add(membership)
            await self._session.flush()

    async def remove_member(self, team_id: str, user_id: str) -> None:
        result = await self._session.execute(
            select(TeamMembership).where(
                and_(TeamMembership.team_id == team_id, TeamMembership.user_id == user_id)
            )
        )
        membership = result.scalar_one_or_none()
        if membership:
            await self._session.delete(membership)
            await self._session.flush()

    async def get_members(self, team_id: str) -> list[User]:
        result = await self._session.execute(
            select(User)
            .join(TeamMembership, TeamMembership.user_id == User.id)
            .where(TeamMembership.team_id == team_id)
        )
        return list(result.scalars().all())

    async def get_documents_only_in_team(self, team_id: str) -> list[Document]:
        """Documents with visibility='team' whose only assigned team is this one."""
        from src.models.document import VisibilityEnum
        # Subquery: document IDs that have access from OTHER teams
        other_teams_subq = (
            select(DocumentTeamAccess.document_id)
            .where(DocumentTeamAccess.team_id != team_id)
        ).scalar_subquery()

        result = await self._session.execute(
            select(Document)
            .join(DocumentTeamAccess, DocumentTeamAccess.document_id == Document.id)
            .where(
                and_(
                    DocumentTeamAccess.team_id == team_id,
                    Document.visibility == VisibilityEnum.TEAM.value,
                    ~Document.id.in_(other_teams_subq),
                )
            )
        )
        return list(result.scalars().unique().all())
