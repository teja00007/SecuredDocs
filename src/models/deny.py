"""DocumentDenyList and ServiceAccount models for advanced access control.

DocumentDenyList
----------------
Explicit deny overrides any allow grant.  A user/team/role listed in
DocumentDenyList is *never* served that document even if other RBAC rules
would permit it.

ServiceAccount
--------------
Non-human identity for CI/CD pipelines and automated ingestion.
A service account has an API key but no password/TOTP; it is scoped to a
single company and an optional list of allowed roles.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class DocumentDenyList(Base):
    """Explicit deny entry — overrides any allow grant for a document.

    At least one of ``user_id`` or ``team_id`` must be set.
    """

    __tablename__ = "document_deny_list"
    __table_args__ = (
        UniqueConstraint("document_id", "user_id", "team_id", name="uq_deny_entry"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Deny a specific user
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Deny an entire team
    team_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    document = relationship("Document", foreign_keys=[document_id], lazy="selectin")
    denied_user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    denied_team = relationship("Team", foreign_keys=[team_id], lazy="selectin")
    creator = relationship("User", foreign_keys=[created_by], lazy="selectin")

    def __repr__(self) -> str:
        target = f"user:{self.user_id}" if self.user_id else f"team:{self.team_id}"
        return f"<DocumentDenyList doc={self.document_id} deny={target}>"


class ServiceAccount(Base):
    """Non-human identity for CI/CD pipelines and automated ingestion.

    A service account authenticates with a long-lived API key (hashed in DB).
    It belongs to a company and carries a set of *roles* (comma-separated).
    """

    __tablename__ = "service_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_service_account_name"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Comma-separated roles: e.g. "ingestion,read"
    roles: Mapped[str] = mapped_column(String(500), nullable=False, default="ingestion")
    # Hashed API key (bcrypt); the raw key is shown only once at creation time
    hashed_api_key: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    company = relationship("Company", foreign_keys=[company_id], lazy="selectin")
    creator = relationship("User", foreign_keys=[created_by], lazy="selectin")

    def get_roles(self) -> list[str]:
        return [r.strip() for r in self.roles.split(",") if r.strip()]

    def has_role(self, role: str) -> bool:
        return role in self.get_roles()

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def __repr__(self) -> str:
        return f"<ServiceAccount {self.name} company={self.company_id}>"
