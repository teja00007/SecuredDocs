"""User, Role, Permission, and junction table models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Boolean, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base




# Junction tables
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String(36), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Password reset
    password_reset_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    password_reset_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # TOTP two-factor authentication
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    totp_backup_codes: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # JSON array of hashed codes

    # OAuth / SAML SSO
    oauth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)    # "google", "microsoft", "saml", or None
    oauth_provider_id: Mapped[str | None] = mapped_column(String(256), nullable=True) # sub/id from the provider

    # Email verification
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    email_verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Multi-tenancy: company (tenant) this user belongs to
    company_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships (use string refs to avoid circular imports)
    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users", lazy="selectin")
    team_memberships = relationship("TeamMembership", back_populates="user", cascade="all, delete-orphan", lazy="selectin")
    company = relationship("Company", back_populates="users", lazy="selectin", foreign_keys="[User.company_id]")

    @property
    def teams(self):
        return [m.team for m in self.team_memberships]

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=True)

    # Relationships
    users: Mapped[list["User"]] = relationship(secondary=user_roles, back_populates="roles", lazy="selectin")
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Role {self.name}>"


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    # Relationships
    roles: Mapped[list["Role"]] = relationship(secondary=role_permissions, back_populates="permissions", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Permission {self.name}>"
