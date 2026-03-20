"""Authentication service — user registration, login, token management."""

import uuid

from src.core.exceptions import AuthenticationError, AuthorizationError
from src.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_refresh_token,
)
from src.models.user import User, Role
from src.repositories.user_repository import UserRepository


class AuthService:
    def __init__(self, user_repo: UserRepository, settings) -> None:
        self._user_repo = user_repo
        self._settings = settings

    async def register_user(self, username: str, email: str, password: str) -> User:
        if await self._user_repo.get_by_username(username):
            raise ValueError(f"Username '{username}' is already taken")
        if await self._user_repo.get_by_email(email):
            raise ValueError(f"Email '{email}' is already registered")

        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            hashed_password=hash_password(password),
            is_active=True,
        )

        # Assign default viewer role
        viewer_role = await self._user_repo.get_role_by_name("viewer")
        created = await self._user_repo.create(user)
        if viewer_role:
            await self._user_repo.assign_role(created.id, viewer_role.id)
            await self._user_repo.get_by_id(created.id)  # refresh

        return created

    async def authenticate_user(self, username_or_email: str, password: str) -> User:
        user = await self._user_repo.get_by_username_or_email(username_or_email)
        if not user:
            raise AuthenticationError("Invalid credentials")
        if not user.is_active:
            raise AuthenticationError("Account is deactivated")
        if not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid credentials")
        return user

    def create_tokens(self, user: User) -> dict:
        role_names = [r.name for r in user.roles]
        team_ids = [m.team_id for m in user.team_memberships]

        access_token = create_access_token(
            data={
                "sub": user.id,
                "username": user.username,
                "roles": role_names,
                "team_ids": team_ids,
                "company_id": user.company_id,
                "is_super_admin": user.is_super_admin,
            },
            secret_key=self._settings.APP_SECRET_KEY,
            algorithm=self._settings.JWT_ALGORITHM,
        )
        refresh_token = create_refresh_token(
            user_id=user.id,
            secret_key=self._settings.APP_SECRET_KEY,
            algorithm=self._settings.JWT_ALGORITHM,
        )
        return {"access_token": access_token, "refresh_token": refresh_token}

    async def refresh_access_token(self, refresh_token: str) -> dict:
        payload = decode_refresh_token(
            refresh_token,
            secret_key=self._settings.APP_SECRET_KEY,
            algorithm=self._settings.JWT_ALGORITHM,
        )
        user = await self._user_repo.get_by_id(payload["sub"])
        if not user or not user.is_active:
            raise AuthenticationError("User not found or deactivated")
        tokens = self.create_tokens(user)
        return {"access_token": tokens["access_token"]}

    async def get_user_by_id(self, user_id: str) -> User:
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise AuthenticationError("User not found")
        return user

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        user = await self._user_repo.get_by_id(user_id)
        if not user:
            raise AuthenticationError("User not found")
        if not verify_password(current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect")
        user.hashed_password = hash_password(new_password)
        await self._user_repo.update(user)

    async def deactivate_user(self, user_id: str) -> None:
        await self._user_repo.deactivate(user_id)
