"""APIKey model — stores hashed API keys for programmatic access."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # sha256 hex digest of the raw key — plaintext is never stored
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # First 8 chars of the full key (e.g. "nxs_a1b2") for display only
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # JSON-encoded list of scope strings, e.g. '["query", "documents:read"]'
    scopes: Mapped[str] = mapped_column(String(512), nullable=False, default='["query"]')
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationship
    user = relationship("User", foreign_keys=[user_id], lazy="select")

    def __repr__(self) -> str:
        return f"<APIKey name={self.name!r} prefix={self.key_prefix!r} active={self.is_active}>"
