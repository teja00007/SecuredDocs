"""
TDD Test Cases — Auth Service (src/services/auth_service.py)
"""
import pytest

from src.services.auth_service import AuthService
from src.repositories.user_repository import UserRepository
from src.core.exceptions import AuthenticationError
from src.core.security import create_access_token, create_refresh_token, decode_access_token


class _Settings:
    APP_SECRET_KEY = "dev-secret-change-me-in-production-min-32-chars"
    JWT_ALGORITHM = "HS256"


_SECRET = "dev-secret-change-me-in-production-min-32-chars"


class TestRegisterUser:
    """auth_service.register_user()"""

    async def test_register_creates_user_in_db(self, db_session):
        svc = AuthService(UserRepository(db_session), _Settings())
        user = await svc.register_user("newuser", "new@example.com", "pass1234")
        assert user.id is not None

    async def test_register_hashes_password(self, db_session):
        svc = AuthService(UserRepository(db_session), _Settings())
        user = await svc.register_user("hashuser", "hash@example.com", "pass1234")
        assert user.hashed_password != "pass1234"
        assert user.hashed_password.startswith("$2b$") or user.hashed_password.startswith("$2a$")

    async def test_register_assigns_default_role(self, db_session):
        from src.models.user import Role
        role = Role(name="viewer", description="Default viewer role")
        db_session.add(role)
        await db_session.commit()
        svc = AuthService(UserRepository(db_session), _Settings())
        user = await svc.register_user("roleuser", "role@example.com", "pass1234")
        assert user is not None

    async def test_register_duplicate_username_raises(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        with pytest.raises(ValueError, match="already taken"):
            await svc.register_user(registered_user.username, "unique@example.com", "pass1234")

    async def test_register_duplicate_email_raises(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        with pytest.raises(ValueError, match="already registered"):
            await svc.register_user("uniqueuser", registered_user.email, "pass1234")

    async def test_register_returns_user_object(self, db_session):
        from src.models.user import User
        svc = AuthService(UserRepository(db_session), _Settings())
        user = await svc.register_user("retuser", "ret@example.com", "pass1234")
        assert isinstance(user, User)
        assert user.username == "retuser"
        assert user.email == "ret@example.com"


class TestAuthenticateUser:
    """auth_service.authenticate_user()"""

    async def test_authenticate_valid_username(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        user = await svc.authenticate_user("testuser", "password123")
        assert user.id == registered_user.id

    async def test_authenticate_valid_email(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        user = await svc.authenticate_user("test@example.com", "password123")
        assert user.id == registered_user.id

    async def test_authenticate_wrong_password_raises(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        with pytest.raises(AuthenticationError):
            await svc.authenticate_user("testuser", "wrongpassword")

    async def test_authenticate_nonexistent_user_raises(self, db_session):
        svc = AuthService(UserRepository(db_session), _Settings())
        with pytest.raises(AuthenticationError):
            await svc.authenticate_user("nobody", "pass1234")

    async def test_authenticate_inactive_user_raises(self, db_session, inactive_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        with pytest.raises(AuthenticationError):
            await svc.authenticate_user("inactive", "password123")


class TestCreateTokens:
    """auth_service.create_tokens()"""

    async def test_returns_access_and_refresh(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        tokens = svc.create_tokens(registered_user)
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert isinstance(tokens["access_token"], str)
        assert isinstance(tokens["refresh_token"], str)

    async def test_access_token_contains_roles(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        tokens = svc.create_tokens(registered_user)
        payload = decode_access_token(
            tokens["access_token"],
            secret_key=_SECRET,
            algorithm="HS256",
        )
        assert "roles" in payload

    async def test_access_token_contains_team_ids(self, db_session, user_with_teams):
        svc = AuthService(UserRepository(db_session), _Settings())
        tokens = svc.create_tokens(user_with_teams)
        payload = decode_access_token(
            tokens["access_token"],
            secret_key=_SECRET,
            algorithm="HS256",
        )
        assert "team_ids" in payload
        assert len(payload["team_ids"]) >= 1


class TestRefreshAccessToken:
    """auth_service.refresh_access_token()"""

    async def test_valid_refresh_returns_new_access(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        refresh = create_refresh_token(
            user_id=registered_user.id,
            secret_key=_SECRET,
            algorithm="HS256",
        )
        result = await svc.refresh_access_token(refresh)
        assert "access_token" in result
        assert isinstance(result["access_token"], str)

    async def test_expired_refresh_raises(self, db_session, expired_refresh):
        svc = AuthService(UserRepository(db_session), _Settings())
        with pytest.raises(AuthenticationError):
            await svc.refresh_access_token(expired_refresh)

    async def test_access_token_as_refresh_raises(self, db_session, registered_user):
        svc = AuthService(UserRepository(db_session), _Settings())
        access = create_access_token(
            data={"sub": registered_user.id, "roles": [], "team_ids": []},
            secret_key=_SECRET,
            algorithm="HS256",
        )
        with pytest.raises(AuthenticationError):
            await svc.refresh_access_token(access)
