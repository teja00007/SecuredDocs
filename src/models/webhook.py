"""Outbound webhook model for external integrations (Zapier, n8n, custom scripts)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class Webhook(Base):
    """Persistent webhook subscription.

    Supported event types:
        "document.uploaded", "document.ingested", "query.completed",
        "user.created", "message.sent", "calendar.event.created"
    """

    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Shared secret used to compute HMAC-SHA256 signatures on every delivery.
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    # JSON-encoded list of event type strings, e.g. '["document.ingested"]'
    events: Mapped[str] = mapped_column(String(1024), nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    owner = relationship("User", foreign_keys=[owner_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<Webhook {self.name!r} url={self.url!r}>"
