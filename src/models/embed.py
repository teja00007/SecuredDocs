"""EmbedToken model — stores embed widget tokens for external embedding."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class EmbedToken(Base):
    __tablename__ = "embed_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # sha256 hex digest of the raw token
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Display prefix (first 8 chars)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Optional: restrict to specific collection_id (NULL = allow any)
    collection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Comma-separated allowed origins (e.g. "https://example.com,https://app.example.com")
    allowed_origins: Mapped[str] = mapped_column(Text, nullable=False, default="*")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", foreign_keys=[created_by], lazy="select")

    def __repr__(self) -> str:
        return f"<EmbedToken name={self.name!r} active={self.is_active}>"
