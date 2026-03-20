"""Calendar event and attendee models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    creator_username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Livekit room name (set when meeting starts / event created with video)
    room_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Recurring event support
    recurrence_rule: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recurrence_parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=True, index=True
    )
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Reminder support
    reminder_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Post-huddle intelligence ───────────────────────────────────────────────
    # AI-generated meeting summary stored directly on the event for quick access.
    meeting_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # FK to the ingested transcript document (searchable via RAG)
    transcript_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # FK to the ingested AI summary document (searchable via RAG)
    summary_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # AI-generated pre-meeting agenda
    agenda: Mapped[str | None] = mapped_column(Text, nullable=True)

    attendees: Mapped[list["EventAttendee"]] = relationship(
        "EventAttendee", back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )

    # Self-referential: child occurrences of a recurring event
    recurrence_children: Mapped[list["CalendarEvent"]] = relationship(
        "CalendarEvent",
        foreign_keys="CalendarEvent.recurrence_parent_id",
        back_populates="recurrence_parent",
        cascade="all, delete-orphan",
        lazy="select",
    )
    recurrence_parent: Mapped["CalendarEvent | None"] = relationship(
        "CalendarEvent",
        foreign_keys="CalendarEvent.recurrence_parent_id",
        back_populates="recurrence_children",
        remote_side="CalendarEvent.id",
    )


class EventAttendee(Base):
    __tablename__ = "event_attendees"

    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calendar_events.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # "pending" | "accepted" | "declined"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    event: Mapped["CalendarEvent"] = relationship("CalendarEvent", back_populates="attendees")
