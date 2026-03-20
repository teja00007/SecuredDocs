"""
TDD Test Cases — User Models (src/models/user.py)

Tests for User, Role, Permission, and junction table ORM models.
"""
import pytest
import uuid as uuid_mod

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.user import User, Role, Permission, user_roles
from src.models.team import Team, TeamMembership
from src.core.security import hash_password


# ============================================================================
# USER MODEL
# ============================================================================

class TestUserModel:
    """Verify User ORM model behavior."""

    @pytest.mark.asyncio
    async def test_create_user(self, db_session):
        """Should create a user with username, email, hashed_password."""
        user = User(
            username="alice",
            email="alice@example.com",
            hashed_password=hash_password("secret"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.username == "alice"
        assert user.email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_user_id_is_uuid(self, db_session):
        """User.id should be auto-generated UUID."""
        user = User(
            username="bob",
            email="bob@example.com",
            hashed_password=hash_password("secret"),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        # Should be a valid UUID string
        parsed = uuid_mod.UUID(user.id)
        assert str(parsed) == user.id

    @pytest.mark.asyncio
    async def test_username_is_unique(self, db_session):
        """Duplicate username should raise IntegrityError."""
        u1 = User(username="dup", email="a@b.com", hashed_password="h")
        u2 = User(username="dup", email="c@d.com", hashed_password="h")
        db_session.add(u1)
        await db_session.commit()
        db_session.add(u2)
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_email_is_unique(self, db_session):
        """Duplicate email should raise IntegrityError."""
        u1 = User(username="u1", email="same@test.com", hashed_password="h")
        u2 = User(username="u2", email="same@test.com", hashed_password="h")
        db_session.add(u1)
        await db_session.commit()
        db_session.add(u2)
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_user_default_is_active(self, db_session):
        """New user should have is_active=True by default."""
        user = User(username="active", email="a@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_user_created_at_auto_set(self, db_session):
        """created_at should be auto-populated on insert."""
        user = User(username="ts", email="ts@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.created_at is not None

    @pytest.mark.asyncio
    async def test_user_updated_at_auto_updates(self, db_session):
        """updated_at should change when user is modified."""
        user = User(username="upd", email="upd@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        original = user.updated_at
        assert original is not None

    @pytest.mark.asyncio
    async def test_user_roles_relationship(self, db_session):
        """user.roles should return list of Role objects."""
        user = User(username="roles_user", email="r@b.com", hashed_password="h")
        role = Role(name="test_role", description="test")
        db_session.add(user)
        db_session.add(role)
        await db_session.flush()
        await db_session.execute(
            user_roles.insert().values(user_id=user.id, role_id=role.id)
        )
        await db_session.commit()
        await db_session.refresh(user)
        assert len(user.roles) == 1
        assert user.roles[0].name == "test_role"

    @pytest.mark.asyncio
    async def test_user_teams_relationship(self, db_session):
        """user.teams should return list of Team objects the user belongs to."""
        user = User(username="team_user", email="t@b.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        team = Team(name="DevTeam", created_by=user.id)
        db_session.add(team)
        await db_session.flush()
        membership = TeamMembership(team_id=team.id, user_id=user.id)
        db_session.add(membership)
        await db_session.commit()
        await db_session.refresh(user)
        assert len(user.teams) == 1
        assert user.teams[0].name == "DevTeam"


# ============================================================================
# ROLE MODEL
# ============================================================================

class TestRoleModel:
    """Verify Role ORM model behavior."""

    @pytest.mark.asyncio
    async def test_create_role(self, db_session):
        """Should create a role with name and description."""
        role = Role(name="editor", description="Can edit")
        db_session.add(role)
        await db_session.commit()
        await db_session.refresh(role)
        assert role.name == "editor"
        assert role.description == "Can edit"

    @pytest.mark.asyncio
    async def test_role_name_is_unique(self, db_session):
        """Duplicate role name should raise IntegrityError."""
        r1 = Role(name="dup_role")
        r2 = Role(name="dup_role")
        db_session.add(r1)
        await db_session.commit()
        db_session.add(r2)
        with pytest.raises(IntegrityError):
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_role_permissions_relationship(self, db_session):
        """role.permissions should return list of Permission objects."""
        from src.models.user import role_permissions as rp_table
        role = Role(name="perm_role")
        perm = Permission(name="test:perm", resource_type="test", action="read")
        db_session.add(role)
        db_session.add(perm)
        await db_session.flush()
        await db_session.execute(
            rp_table.insert().values(role_id=role.id, permission_id=perm.id)
        )
        await db_session.commit()
        await db_session.refresh(role)
        assert len(role.permissions) == 1
        assert role.permissions[0].name == "test:perm"

    @pytest.mark.asyncio
    async def test_role_users_relationship(self, db_session):
        """role.users should return list of User objects assigned this role."""
        role = Role(name="users_role")
        user = User(username="role_test", email="rt@b.com", hashed_password="h")
        db_session.add(role)
        db_session.add(user)
        await db_session.flush()
        await db_session.execute(
            user_roles.insert().values(user_id=user.id, role_id=role.id)
        )
        await db_session.commit()
        await db_session.refresh(role)
        assert len(role.users) == 1
        assert role.users[0].username == "role_test"


# ============================================================================
# PERMISSION MODEL
# ============================================================================

class TestPermissionModel:
    """Verify Permission ORM model behavior."""

    @pytest.mark.asyncio
    async def test_create_permission(self, db_session):
        """Should create permission with name, resource_type, action."""
        perm = Permission(name="doc:write", resource_type="document", action="write")
        db_session.add(perm)
        await db_session.commit()
        await db_session.refresh(perm)
        assert perm.name == "doc:write"
        assert perm.resource_type == "document"
        assert perm.action == "write"

    @pytest.mark.asyncio
    async def test_permission_name_is_unique(self, db_session):
        """Duplicate permission name should raise IntegrityError."""
        p1 = Permission(name="dup:perm", resource_type="x", action="y")
        p2 = Permission(name="dup:perm", resource_type="x", action="y")
        db_session.add(p1)
        await db_session.commit()
        db_session.add(p2)
        with pytest.raises(IntegrityError):
            await db_session.commit()


# ============================================================================
# USER-ROLE JUNCTION
# ============================================================================

class TestUserRoleJunction:
    """Verify many-to-many User <-> Role relationship."""

    @pytest.mark.asyncio
    async def test_assign_role_to_user(self, db_session):
        """Adding a role to user.roles should persist."""
        user = User(username="jr1", email="jr1@b.com", hashed_password="h")
        role = Role(name="jr_role1")
        db_session.add(user)
        db_session.add(role)
        await db_session.flush()
        await db_session.execute(
            user_roles.insert().values(user_id=user.id, role_id=role.id)
        )
        await db_session.commit()
        await db_session.refresh(user)
        assert len(user.roles) == 1

    @pytest.mark.asyncio
    async def test_user_can_have_multiple_roles(self, db_session):
        """A user should be able to have admin + analyst roles."""
        user = User(username="multi", email="multi@b.com", hashed_password="h")
        r1 = Role(name="multi_r1")
        r2 = Role(name="multi_r2")
        db_session.add_all([user, r1, r2])
        await db_session.flush()
        await db_session.execute(
            user_roles.insert().values(user_id=user.id, role_id=r1.id)
        )
        await db_session.execute(
            user_roles.insert().values(user_id=user.id, role_id=r2.id)
        )
        await db_session.commit()
        await db_session.refresh(user)
        assert len(user.roles) == 2

    @pytest.mark.asyncio
    async def test_remove_role_from_user(self, db_session):
        """Removing a role from user.roles should persist."""
        user = User(username="rmr", email="rmr@b.com", hashed_password="h")
        role = Role(name="rmr_role")
        db_session.add(user)
        db_session.add(role)
        await db_session.flush()
        await db_session.execute(
            user_roles.insert().values(user_id=user.id, role_id=role.id)
        )
        await db_session.commit()
        await db_session.refresh(user)
        assert len(user.roles) == 1

        # Remove
        await db_session.execute(
            user_roles.delete().where(
                (user_roles.c.user_id == user.id) & (user_roles.c.role_id == role.id)
            )
        )
        await db_session.commit()
        await db_session.refresh(user)
        assert len(user.roles) == 0

    @pytest.mark.asyncio
    async def test_duplicate_role_assignment_raises(self, db_session):
        """Assigning the same role twice should raise IntegrityError."""
        user = User(username="dup_jr", email="dup_jr@b.com", hashed_password="h")
        role = Role(name="dup_jr_role")
        db_session.add(user)
        db_session.add(role)
        await db_session.flush()
        await db_session.execute(
            user_roles.insert().values(user_id=user.id, role_id=role.id)
        )
        await db_session.commit()
        with pytest.raises(IntegrityError):
            await db_session.execute(
                user_roles.insert().values(user_id=user.id, role_id=role.id)
            )
            await db_session.commit()
