"""Connector and ConnectorDocument ORM models for external document sync."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class Connector(Base):
    __tablename__ = "connectors"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "google_drive" | "confluence" | "web_url" | "notion"
    config: Mapped[str] = mapped_column(
        String(4096), nullable=False, default="{}"
    )  # JSON blob — provider-specific config
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    team_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("teams.id"), nullable=True
    )
    collection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("collections.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # "active" | "paused" | "error"
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_interval_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60
    )
    total_docs_synced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    connector_documents: Mapped[list["ConnectorDocument"]] = relationship(
        back_populates="connector",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Connector {self.name} ({self.type})>"


class ConnectorDocument(Base):
    __tablename__ = "connector_documents"
    __table_args__ = (
        UniqueConstraint("connector_id", "external_id", name="uq_connector_external"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    connector_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    connector: Mapped["Connector"] = relationship(back_populates="connector_documents")

    def __repr__(self) -> str:
        return f"<ConnectorDocument {self.title} (connector={self.connector_id})>"
