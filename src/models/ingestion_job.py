"""IngestionJob model — tracks async document ingestion progress.

Each time a document is ingested (chunked + embedded) an IngestionJob row is
created.  The Celery worker updates ``progress_pct``, ``status``, and
``error_message`` as work proceeds.  A WebSocket endpoint pushes updates to
connected clients so the UI can show a real-time progress bar.

Status flow:
    pending → processing → completed
                         ↘ failed
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class IngestionJobStatus(str):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionJob(Base):
    """Tracks the state of a document ingestion / embedding job."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Who triggered the ingestion (user or service account)
    triggered_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Progress tracking
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=IngestionJobStatus.PENDING, index=True
    )
    progress_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Error details
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    document = relationship("Document", foreign_keys=[document_id], lazy="selectin")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def mark_started(self) -> None:
        self.status = IngestionJobStatus.PROCESSING
        self.started_at = datetime.now(timezone.utc)

    def update_progress(self, processed: int, total: int) -> None:
        self.processed_chunks = processed
        self.total_chunks = total
        self.progress_pct = round((processed / total * 100) if total > 0 else 0.0, 1)

    def mark_completed(self) -> None:
        self.status = IngestionJobStatus.COMPLETED
        self.progress_pct = 100.0
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self, error: str) -> None:
        self.status = IngestionJobStatus.FAILED
        self.error_message = error
        self.completed_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "total_chunks": self.total_chunks,
            "processed_chunks": self.processed_chunks,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self) -> str:
        return f"<IngestionJob {self.id} doc={self.document_id} {self.status} {self.progress_pct}%>"
