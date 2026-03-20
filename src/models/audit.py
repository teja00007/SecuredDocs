"""Audit log models — QueryLog, IngestionLog, DocumentAuditLog, TeamAuditLog."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class DocumentAction(str, enum.Enum):
    CREATED = "created"
    VISIBILITY_CHANGED = "visibility_changed"
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    DELETED = "deleted"


class TeamAction(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    MEMBER_ADDED = "member_added"
    MEMBER_REMOVED = "member_removed"
    DELETED = "deleted"


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunks_retrieved: Mapped[int] = mapped_column(Integer, default=0)
    response_length: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Eval-dashboard columns (all nullable — back-filled on new queries)
    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    chunk_count_retrieved: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_has_sources: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    answer_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_retrieval_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_generation_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Optional: store which collection was queried for per-collection analytics
    collection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    user = relationship("User", lazy="selectin")


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    document = relationship("Document", lazy="selectin")
    user = relationship("User", lazy="selectin")


class DocumentAuditLog(Base):
    __tablename__ = "document_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(
        Enum(DocumentAction, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    old_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    document = relationship("Document", lazy="selectin")
    user = relationship("User", lazy="selectin")


class TeamAuditLog(Base):
    __tablename__ = "team_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(
        Enum(TeamAction, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    target_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    team = relationship("Team", lazy="selectin")
    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    target_user = relationship("User", foreign_keys=[target_user_id], lazy="selectin")
