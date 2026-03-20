"""Invite model for invite-only registration flow."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, ForeignKey, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    invited_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # JSON list of role names to assign on registration, e.g. '["user"]'
    roles: Mapped[str] = mapped_column(String(512), nullable=False, default='["viewer"]')
    # JSON list of team IDs to auto-add to, e.g. '[]'
    team_ids: Mapped[str] = mapped_column(String(1024), nullable=False, default="[]")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc) + timedelta(days=7),
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    invited_by = relationship("User", foreign_keys=[invited_by_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<Invite {self.email} by {self.invited_by_id}>"
