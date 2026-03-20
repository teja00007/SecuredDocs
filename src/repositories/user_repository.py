"""User data access layer."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User, Role
from src.models.team import Team, TeamMembership


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_username_or_email(self, identifier: str) -> User | None:
        result = await self._session.execute(
            select(User).where(
                (User.username == identifier) | (User.email == identifier)
            )
        )
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def update(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def deactivate(self, user_id: str) -> None:
        user = await self.get_by_id(user_id)
        if user:
            user.is_active = False
            await self._session.flush()

    async def list_all(self, skip: int = 0, limit: int = 50) -> list[User]:
        result = await self._session.execute(
            select(User).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def get_user_roles(self, user_id: str) -> list[Role]:
        user = await self.get_by_id(user_id)
        if not user:
            return []
        return list(user.roles)

    async def get_user_teams(self, user_id: str) -> list[Team]:
        result = await self._session.execute(
            select(Team)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(TeamMembership.user_id == user_id)
        )
        return list(result.scalars().all())

    async def assign_role(self, user_id: str, role_id: str) -> None:
        user = await self.get_by_id(user_id)
        result = await self._session.execute(select(Role).where(Role.id == role_id))
        role = result.scalar_one_or_none()
        if user and role and role not in user.roles:
            user.roles.append(role)
            await self._session.flush()

    async def remove_role(self, user_id: str, role_id: str) -> None:
        user = await self.get_by_id(user_id)
        result = await self._session.execute(select(Role).where(Role.id == role_id))
        role = result.scalar_one_or_none()
        if user and role and role in user.roles:
            user.roles.remove(role)
            await self._session.flush()

    async def get_role_by_name(self, name: str) -> Role | None:
        result = await self._session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()
