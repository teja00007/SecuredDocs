"""Calendar events — CRUD + RSVP + Livekit room generation + iCal import/export.

─────────────────────────────────────────────────────────────────────────────
POST-HUDDLE INTELLIGENCE — NEW DB COLUMNS
─────────────────────────────────────────────────────────────────────────────
The following columns must be added to the calendar_events table.
Add these entries to _add_missing_columns() in src/main.py:

    ("calendar_events", "meeting_notes",           "TEXT"),
    ("calendar_events", "transcript_document_id",  "VARCHAR(36)"),
    ("calendar_events", "summary_document_id",     "VARCHAR(36)"),
    ("calendar_events", "agenda",                  "TEXT"),
─────────────────────────────────────────────────────────────────────────────
"""

import io
import logging
import uuid
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import (
    get_current_user, get_db, get_rag_service, get_settings,
)
from src.config import Settings
from src.core.rbac import UserContext, build_visibility_filter
from src.models.calendar import CalendarEvent, EventAttendee
from src.services.ingestion_service import IngestionService
from src.services.rag_service import RAGService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])

_TRANSCRIPT_UPLOAD_DIR = Path("data/uploads/transcripts")

_MAX_RECURRENCE_OCCURRENCES = 50


# ── Schemas ───────────────────────────────────────────────────────────────────

class AttendeeOut(BaseModel):
    user_id: str
    username: str
    status: str


class EventOut(BaseModel):
    id: str
    title: str
    description: str | None
    location: str | None
    start_time: datetime
    end_time: datetime
    created_by: str
    creator_username: str
    room_name: str | None
    created_at: datetime
    attendees: list[AttendeeOut]
    recurrence_rule: str | None
    recurrence_parent_id: str | None
    is_cancelled: bool
    reminder_minutes: int | None


class CreateEventRequest(BaseModel):
    title: str
    description: str | None = None
    location: str | None = None
    start_time: datetime
    end_time: datetime
    attendee_ids: list[str] = []
    attendee_usernames: dict[str, str] = {}  # user_id → username
    with_video: bool = False
    recurrence_rule: str | None = None
    reminder_minutes: int | None = None


class UpdateEventRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    reminder_minutes: int | None = None


class RSVPRequest(BaseModel):
    status: str  # "accepted" | "declined"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event_out(ev: CalendarEvent) -> EventOut:
    return EventOut(
        id=ev.id,
        title=ev.title,
        description=ev.description,
        location=getattr(ev, "location", None),
        start_time=ev.start_time,
        end_time=ev.end_time,
        created_by=ev.created_by,
        creator_username=ev.creator_username,
        room_name=ev.room_name,
        created_at=ev.created_at,
        attendees=[AttendeeOut(user_id=a.user_id, username=a.username, status=a.status) for a in ev.attendees],
        recurrence_rule=getattr(ev, "recurrence_rule", None),
        recurrence_parent_id=getattr(ev, "recurrence_parent_id", None),
        is_cancelled=getattr(ev, "is_cancelled", False),
        reminder_minutes=getattr(ev, "reminder_minutes", None),
    )


def _make_room_name() -> str:
    return f"meet-{secrets.token_urlsafe(8)}"


def _generate_recurrence_children(
    parent: CalendarEvent,
    recurrence_rule: str,
    creator_username: str,
) -> list[CalendarEvent]:
    """Generate up to _MAX_RECURRENCE_OCCURRENCES child CalendarEvent objects."""
    try:
        from dateutil.rrule import rrulestr
    except ImportError:
        return []

    duration = parent.end_time - parent.start_time
    # Strip the first occurrence (same as parent start)
    rule = rrulestr(recurrence_rule, dtstart=parent.start_time, ignoretz=False)
    children: list[CalendarEvent] = []
    count = 0
    for dt in rule:
        if count == 0:
            # Skip the first occurrence — it is the parent itself
            count += 1
            continue
        if count > _MAX_RECURRENCE_OCCURRENCES:
            break
        child_start = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        child_end = child_start + duration
        child = CalendarEvent(
            id=str(uuid.uuid4()),
            title=parent.title,
            description=parent.description,
            location=parent.location,
            start_time=child_start,
            end_time=child_end,
            created_by=parent.created_by,
            creator_username=creator_username,
            room_name=parent.room_name,
            recurrence_parent_id=parent.id,
            recurrence_rule=None,
            is_cancelled=False,
            reminder_minutes=parent.reminder_minutes,
            reminder_sent=False,
        )
        children.append(child)
        count += 1
    return children


async def _copy_attendees(db: AsyncSession, source_event: CalendarEvent, target_event_id: str) -> None:
    """Copy attendees from source event to a new event."""
    for a in source_event.attendees:
        db.add(EventAttendee(
            event_id=target_event_id,
            user_id=a.user_id,
            username=a.username,
            status=a.status,
        ))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/events", response_model=list[EventOut])
async def list_events(
    start: datetime | None = Query(default=None, description="Filter events starting at or after this datetime"),
    end: datetime | None = Query(default=None, description="Filter events starting before this datetime"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return events the user created or is invited to, optionally filtered by date range."""
    invited_subq = (
        select(EventAttendee.event_id).where(EventAttendee.user_id == user.user_id)
    ).scalar_subquery()

    stmt = select(CalendarEvent).where(
        or_(CalendarEvent.created_by == user.user_id, CalendarEvent.id.in_(invited_subq))
    )

    if start is not None:
        start_aware = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        stmt = stmt.where(CalendarEvent.start_time >= start_aware)
    if end is not None:
        end_aware = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        stmt = stmt.where(CalendarEvent.start_time < end_aware)

    stmt = stmt.order_by(CalendarEvent.start_time)
    result = await db.execute(stmt)
    events = list(result.scalars().unique().all())
    await db.commit()
    return [_event_out(e) for e in events]


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: CreateEventRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from src.repositories.user_repository import UserRepository
    repo = UserRepository(db)
    db_user = await repo.get_by_id(user.user_id)
    creator_username = db_user.username if db_user else user.user_id

    ev = CalendarEvent(
        id=str(uuid.uuid4()),
        title=body.title,
        description=body.description,
        location=body.location,
        start_time=body.start_time,
        end_time=body.end_time,
        created_by=user.user_id,
        creator_username=creator_username,
        room_name=_make_room_name() if body.with_video else None,
        recurrence_rule=body.recurrence_rule,
        recurrence_parent_id=None,
        is_cancelled=False,
        reminder_minutes=body.reminder_minutes,
        reminder_sent=False,
    )
    db.add(ev)
    await db.flush()

    # Creator is always an accepted attendee
    db.add(EventAttendee(event_id=ev.id, user_id=user.user_id, username=creator_username, status="accepted"))

    for uid in body.attendee_ids:
        if uid == user.user_id:
            continue
        uname = body.attendee_usernames.get(uid, uid)
        db.add(EventAttendee(event_id=ev.id, user_id=uid, username=uname, status="pending"))

    await db.flush()

    # Generate recurring children
    if body.recurrence_rule:
        children = _generate_recurrence_children(ev, body.recurrence_rule, creator_username)
        for child in children:
            db.add(child)
            await db.flush()
            await _copy_attendees(db, ev, child.id)
            await db.flush()

    await db.refresh(ev)
    await db.commit()
    return _event_out(ev)


@router.get("/events/{event_id}", response_model=EventOut)
async def get_event(
    event_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ev = (await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    is_involved = ev.created_by == user.user_id or any(a.user_id == user.user_id for a in ev.attendees)
    if not is_involved:
        raise HTTPException(status_code=403, detail="Access denied")
    await db.commit()
    return _event_out(ev)


@router.patch("/events/{event_id}", response_model=EventOut)
async def update_event(
    event_id: str,
    body: UpdateEventRequest,
    edit_mode: str = Query(default="this", description="'this' | 'this_and_following' | 'all'"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ev = (await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    if ev.created_by != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only creator can edit")

    if edit_mode not in ("this", "this_and_following", "all"):
        raise HTTPException(status_code=400, detail="edit_mode must be 'this', 'this_and_following', or 'all'")

    def _apply_update(event: CalendarEvent) -> None:
        if body.title is not None:
            event.title = body.title
        if body.description is not None:
            event.description = body.description
        if body.location is not None:
            event.location = body.location
        if body.start_time is not None:
            event.start_time = body.start_time
        if body.end_time is not None:
            event.end_time = body.end_time
        if body.reminder_minutes is not None:
            event.reminder_minutes = body.reminder_minutes

    if edit_mode == "this":
        _apply_update(ev)

    elif edit_mode == "this_and_following":
        _apply_update(ev)
        # Update all children with start_time >= this event's start_time
        parent_id = ev.recurrence_parent_id or ev.id
        result = await db.execute(
            select(CalendarEvent).where(
                and_(
                    CalendarEvent.recurrence_parent_id == parent_id,
                    CalendarEvent.start_time >= ev.start_time,
                )
            )
        )
        for child in result.scalars().all():
            _apply_update(child)

    elif edit_mode == "all":
        # Find the root parent
        root = ev
        if ev.recurrence_parent_id:
            parent_res = await db.execute(
                select(CalendarEvent).where(CalendarEvent.id == ev.recurrence_parent_id)
            )
            parent = parent_res.scalar_one_or_none()
            if parent:
                root = parent

        _apply_update(root)

        # Update all children and optionally regenerate them
        result = await db.execute(
            select(CalendarEvent).where(CalendarEvent.recurrence_parent_id == root.id)
        )
        children = list(result.scalars().all())
        for child in children:
            _apply_update(child)

        # If recurrence_rule still exists and title/times changed, regenerate children
        if root.recurrence_rule and (body.start_time is not None or body.end_time is not None):
            # Delete existing children and regenerate
            for child in children:
                await db.delete(child)
            await db.flush()

            from src.repositories.user_repository import UserRepository
            repo = UserRepository(db)
            db_user = await repo.get_by_id(user.user_id)
            creator_username = db_user.username if db_user else user.user_id

            new_children = _generate_recurrence_children(root, root.recurrence_rule, creator_username)
            for child in new_children:
                db.add(child)
                await db.flush()
                await _copy_attendees(db, root, child.id)
                await db.flush()

    await db.commit()
    await db.refresh(ev)
    return _event_out(ev)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    delete_mode: str = Query(default="this", description="'this' | 'this_and_following' | 'all'"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ev = (await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    if ev.created_by != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only creator can delete")

    if delete_mode not in ("this", "this_and_following", "all"):
        raise HTTPException(status_code=400, detail="delete_mode must be 'this', 'this_and_following', or 'all'")

    if delete_mode == "this":
        # Just cancel / delete this single occurrence
        if ev.recurrence_parent_id:
            ev.is_cancelled = True
        else:
            await db.delete(ev)

    elif delete_mode == "this_and_following":
        # Delete this occurrence and all future children
        parent_id = ev.recurrence_parent_id or ev.id
        result = await db.execute(
            select(CalendarEvent).where(
                and_(
                    CalendarEvent.recurrence_parent_id == parent_id,
                    CalendarEvent.start_time >= ev.start_time,
                )
            )
        )
        for child in result.scalars().all():
            await db.delete(child)
        if ev.recurrence_parent_id:
            ev.is_cancelled = True
        else:
            await db.delete(ev)

    elif delete_mode == "all":
        # Delete the parent and all children
        root_id = ev.recurrence_parent_id or ev.id
        root = ev
        if ev.recurrence_parent_id:
            parent_res = await db.execute(
                select(CalendarEvent).where(CalendarEvent.id == ev.recurrence_parent_id)
            )
            root = parent_res.scalar_one_or_none() or ev

        result = await db.execute(
            select(CalendarEvent).where(CalendarEvent.recurrence_parent_id == root_id)
        )
        for child in result.scalars().all():
            await db.delete(child)
        await db.delete(root)

    await db.commit()


@router.post("/events/{event_id}/rsvp", response_model=EventOut)
async def rsvp_event(
    event_id: str,
    body: RSVPRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in ("accepted", "declined"):
        raise HTTPException(status_code=400, detail="status must be 'accepted' or 'declined'")

    ev = (await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    attendee = next((a for a in ev.attendees if a.user_id == user.user_id), None)
    if not attendee:
        raise HTTPException(status_code=403, detail="You are not invited to this event")

    attendee.status = body.status
    await db.commit()
    await db.refresh(ev)
    return _event_out(ev)


@router.post("/events/{event_id}/room", response_model=EventOut)
async def ensure_room(
    event_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach a video room to an existing event (lazy creation)."""
    ev = (await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    if ev.created_by != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only creator can add room")
    if not ev.room_name:
        ev.room_name = _make_room_name()
        await db.commit()
        await db.refresh(ev)
    return _event_out(ev)


# ── iCal Export ───────────────────────────────────────────────────────────────

def _build_ical_calendar(events: list[CalendarEvent]) -> bytes:
    """Build an iCalendar VCALENDAR bytes from a list of CalendarEvent objects."""
    from icalendar import Calendar, Event as ICalEvent
    cal = Calendar()
    cal.add("prodid", "-//Nexus Enterprise//Nexus Calendar//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")

    for ev in events:
        iev = ICalEvent()
        iev.add("uid", ev.id)
        iev.add("summary", ev.title)
        iev.add("dtstart", ev.start_time)
        iev.add("dtend", ev.end_time)
        iev.add("dtstamp", datetime.now(timezone.utc))
        if ev.description:
            iev.add("description", ev.description)
        if getattr(ev, "location", None):
            iev.add("location", ev.location)
        if getattr(ev, "recurrence_rule", None) and not ev.recurrence_parent_id:
            iev.add("rrule", _parse_rrule_str(ev.recurrence_rule))
        cal.add_component(iev)

    return cal.to_ical()


def _parse_rrule_str(rrule_str: str) -> dict:
    """Convert a raw RRULE string like 'FREQ=WEEKLY;BYDAY=MO' into a dict for icalendar."""
    parts: dict[str, object] = {}
    for part in rrule_str.split(";"):
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip().upper()
        val = val.strip()
        if key == "FREQ":
            parts["freq"] = val
        elif key == "COUNT":
            parts["count"] = int(val)
        elif key == "INTERVAL":
            parts["interval"] = int(val)
        elif key == "BYDAY":
            parts["byday"] = val
        elif key == "UNTIL":
            parts["until"] = val
        else:
            parts[key.lower()] = val
    return parts


@router.get("/export.ics")
async def export_calendar_ics(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all user events as an iCal (.ics) file."""
    invited_subq = (
        select(EventAttendee.event_id).where(EventAttendee.user_id == user.user_id)
    ).scalar_subquery()

    result = await db.execute(
        select(CalendarEvent).where(
            or_(CalendarEvent.created_by == user.user_id, CalendarEvent.id.in_(invited_subq))
        ).order_by(CalendarEvent.start_time)
    )
    events = list(result.scalars().unique().all())
    await db.commit()

    ics_bytes = _build_ical_calendar(events)
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="nexus-calendar.ics"'},
    )


@router.get("/events/{event_id}/ics")
async def export_event_ics(
    event_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export a single event as an .ics file."""
    ev = (await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    is_involved = ev.created_by == user.user_id or any(a.user_id == user.user_id for a in ev.attendees)
    if not is_involved:
        raise HTTPException(status_code=403, detail="Access denied")
    await db.commit()

    ics_bytes = _build_ical_calendar([ev])
    safe_title = ev.title.replace(" ", "_")[:40]
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.ics"'},
    )


# ── Post-Huddle Intelligence ──────────────────────────────────────────────────


def _safe_filename(text: str, max_len: int = 40) -> str:
    """Sanitize a string for use in a filename (no spaces, limited length)."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)[:max_len]


async def _run_transcript_pipeline(
    event_id: str,
    audio_bytes: bytes,
    audio_filename: str,
    user_id: str,
    settings: Settings,
) -> None:
    """Background task: transcribe → summarise → ingest transcript + summary docs.

    Opens fresh DB sessions (safe for BackgroundTasks / after request lifecycle).
    """
    from src.db.session import get_async_engine, get_session_factory
    from src.repositories.document_repository import DocumentRepository
    from src.repositories.audit_repository import AuditRepository
    from src.services.transcription_service import TranscriptionService
    from src.services.embedding_service import OllamaEmbeddingService
    from src.vectorstore import get_vector_store
    from src.llm import get_llm
    from src.models.document import Document
    from src.core.interfaces import LLMResponse

    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    # ── Step 1: Fetch event ────────────────────────────────────────────────────
    async with factory() as session:
        ev = (await session.execute(
            select(CalendarEvent).where(CalendarEvent.id == event_id)
        )).scalar_one_or_none()
        if not ev:
            logger.error("Transcript pipeline: event %s not found", event_id)
            return
        event_title = ev.title
        event_date  = ev.start_time.strftime("%Y-%m-%d")
        # Attendee user_ids for confidential document access
        attendee_ids = [a.user_id for a in ev.attendees]

    # ── Step 2: Transcribe audio ───────────────────────────────────────────────
    transcription_svc = TranscriptionService(settings=settings)
    try:
        transcript_text = await transcription_svc.transcribe_from_bytes(
            audio_bytes, audio_filename
        )
    except Exception as exc:
        logger.error("Transcript pipeline: transcription failed for event %s: %s", event_id, exc)
        return

    # ── Step 3: Generate AI summary ────────────────────────────────────────────
    llm = get_llm(settings)
    summary_prompt = (
        "You are summarizing a meeting transcript. Extract: "
        "1) Key decisions made, 2) Action items with owners, "
        "3) Main discussion points. Format as markdown.\n\n"
        f"Transcript:\n{transcript_text[:12000]}"
    )
    messages = [
        {"role": "system", "content": "You are Nexus, a helpful enterprise AI assistant."},
        {"role": "user", "content": summary_prompt},
    ]
    try:
        import asyncio as _asyncio
        response: LLMResponse = await _asyncio.wait_for(
            llm.generate(messages, temperature=0.1), timeout=120.0
        )
        summary_text = (response.content or "").strip()
    except Exception as exc:
        logger.error("Transcript pipeline: LLM summarization failed for event %s: %s", event_id, exc)
        summary_text = ""

    # ── Step 4: Save transcript text to disk and ingest ────────────────────────
    safe_title = _safe_filename(event_title)
    transcript_filename = f"{safe_title}_transcript_{event_date}.txt"
    summary_filename    = f"{safe_title}_summary_{event_date}.md"

    transcript_doc_id = str(uuid.uuid4())
    summary_doc_id    = str(uuid.uuid4())

    transcript_dir = _TRANSCRIPT_UPLOAD_DIR / event_id
    transcript_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = transcript_dir / transcript_filename
    transcript_path.write_text(transcript_text, encoding="utf-8")

    summary_path = transcript_dir / summary_filename
    summary_path.write_text(summary_text or "No summary generated.", encoding="utf-8")

    # Attendee IDs as pipe-delimited string for RBAC
    allowed_users_str = "|" + "|".join(attendee_ids) + "|" if attendee_ids else ""

    # Shared visibility metadata for both documents
    def _vis_meta(doc_id: str, filename: str) -> dict:
        return {
            "owner_id": user_id,
            "filename": filename,
            "visibility": "confidential",
            "chunking_strategy": None,
            "collection_id": "",
            "allowed_teams": "",
            "allowed_users": allowed_users_str,
            "channel_id": "",
        }

    # Create DB records for both documents
    async with factory() as session:
        doc_repo   = DocumentRepository(session)
        audit_repo = AuditRepository(session)

        transcript_doc = Document(
            id=transcript_doc_id,
            filename=transcript_filename,
            file_type=".txt",
            file_size=len(transcript_text.encode()),
            visibility="confidential",
            collection_id=None,
            owner_id=user_id,
            chunking_strategy=None,
            file_path=str(transcript_path),
            status="pending",
            current_version=1,
        )
        await doc_repo.create(transcript_doc)
        if attendee_ids:
            await doc_repo.set_user_access(transcript_doc_id, attendee_ids)

        summary_doc = Document(
            id=summary_doc_id,
            filename=summary_filename,
            file_type=".md",
            file_size=len((summary_text or "").encode()),
            visibility="confidential",
            collection_id=None,
            owner_id=user_id,
            chunking_strategy=None,
            file_path=str(summary_path),
            status="pending",
            current_version=1,
        )
        await doc_repo.create(summary_doc)
        if attendee_ids:
            await doc_repo.set_user_access(summary_doc_id, attendee_ids)

        await session.commit()

    # ── Step 5: Ingest both documents into the vector store ───────────────────
    embedding_svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    vector_store = get_vector_store(settings)

    async with factory() as session:
        doc_repo2   = DocumentRepository(session)
        audit_repo2 = AuditRepository(session)
        ingestion_svc = IngestionService(
            document_repo=doc_repo2,
            audit_repo=audit_repo2,
            embedding_service=embedding_svc,
            vector_store=vector_store,
            settings=settings,
        )

    # Run ingestion using fresh sessions (IngestionService opens its own sessions)
    try:
        await ingestion_svc.ingest_document(
            document_id=transcript_doc_id,
            file_path=str(transcript_path),
            file_type=".txt",
            visibility_metadata=_vis_meta(transcript_doc_id, transcript_filename),
        )
    except Exception as exc:
        logger.error("Transcript ingestion failed for event %s: %s", event_id, exc)

    try:
        await ingestion_svc.ingest_document(
            document_id=summary_doc_id,
            file_path=str(summary_path),
            file_type=".md",
            visibility_metadata=_vis_meta(summary_doc_id, summary_filename),
        )
    except Exception as exc:
        logger.error("Summary ingestion failed for event %s: %s", event_id, exc)

    # ── Step 6: Update CalendarEvent record ────────────────────────────────────
    async with factory() as session:
        ev2 = (await session.execute(
            select(CalendarEvent).where(CalendarEvent.id == event_id)
        )).scalar_one_or_none()
        if ev2:
            ev2.meeting_notes          = summary_text
            ev2.transcript_document_id = transcript_doc_id
            ev2.summary_document_id    = summary_doc_id
            await session.commit()
            logger.info(
                "Transcript pipeline complete for event %s — transcript_doc=%s summary_doc=%s",
                event_id, transcript_doc_id, summary_doc_id,
            )


@router.post("/events/{event_id}/transcript", status_code=status.HTTP_202_ACCEPTED)
async def upload_transcript(
    event_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Upload an audio recording of a meeting.

    Accepted formats: mp3, mp4, wav, m4a, ogg, webm (LiveKit WebM/Opus).
    Transcription + summarisation + RAG ingestion happen asynchronously.
    Returns immediately with {"status": "processing"} so the client can poll
    GET /calendar/events/{id}/transcript for completion.
    """
    _ALLOWED_AUDIO = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".webm"}

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_AUDIO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported audio format '{suffix}'. Allowed: {sorted(_ALLOWED_AUDIO)}",
        )

    ev = (await db.execute(
        select(CalendarEvent).where(CalendarEvent.id == event_id)
    )).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    is_involved = ev.created_by == user.user_id or any(
        a.user_id == user.user_id for a in ev.attendees
    )
    if not is_involved:
        raise HTTPException(status_code=403, detail="Access denied")

    audio_bytes = await file.read()
    max_bytes   = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(audio_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Audio file exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB",
        )

    # Mark event as "processing" immediately so the GET endpoint can return it
    ev.meeting_notes          = None  # reset if re-uploading
    ev.transcript_document_id = None
    ev.summary_document_id    = None
    await db.commit()

    background_tasks.add_task(
        _run_transcript_pipeline,
        event_id=event_id,
        audio_bytes=audio_bytes,
        audio_filename=file.filename or f"recording{suffix}",
        user_id=user.user_id,
        settings=settings,
    )

    return {
        "status": "processing",
        "message": "Audio received. Transcription and summarisation are running in the background.",
        "event_id": event_id,
    }


@router.get("/events/{event_id}/transcript")
async def get_transcript(
    event_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the meeting notes (AI summary) and linked document IDs for an event.

    404 if no transcript has been uploaded yet.
    """
    ev = (await db.execute(
        select(CalendarEvent).where(CalendarEvent.id == event_id)
    )).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    is_involved = ev.created_by == user.user_id or any(
        a.user_id == user.user_id for a in ev.attendees
    )
    if not is_involved:
        raise HTTPException(status_code=403, detail="Access denied")

    # If neither document ID is set, no transcript has been uploaded
    if not ev.transcript_document_id and not ev.summary_document_id and ev.meeting_notes is None:
        raise HTTPException(status_code=404, detail="No transcript uploaded for this event")

    await db.commit()
    return {
        "meeting_notes":          ev.meeting_notes,
        "transcript_document_id": ev.transcript_document_id,
        "summary_document_id":    ev.summary_document_id,
    }


# ── AI Meeting Agenda Generator ───────────────────────────────────────────────


class AgendaRequest(BaseModel):
    context: str | None = None  # Optional: what this meeting is about


@router.post("/events/{event_id}/agenda")
async def generate_agenda(
    event_id: str,
    body: AgendaRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rag_svc: RAGService = Depends(get_rag_service),
    settings: Settings = Depends(get_settings),
):
    """Generate an AI meeting agenda using relevant documents from the knowledge base.

    Retrieves up to 10 RAG documents matching the event context, feeds them to
    the LLM, stores the result in calendar_events.agenda, and returns it.
    """
    ev = (await db.execute(
        select(CalendarEvent).where(CalendarEvent.id == event_id)
    )).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    is_involved = ev.created_by == user.user_id or any(
        a.user_id == user.user_id for a in ev.attendees
    )
    if not is_involved:
        raise HTTPException(status_code=403, detail="Access denied")

    context = (body.context or "").strip()

    # Build a rich search query from event fields
    search_query = " ".join(filter(None, [ev.title, context, ev.description]))

    # Retrieve relevant background documents via RAG
    from src.core.rbac import build_visibility_filter
    from src.services.retrieval_service import RetrievalService
    from src.services.embedding_service import OllamaEmbeddingService
    from src.vectorstore import get_vector_store

    embedding_svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    vector_store  = get_vector_store(settings)
    retrieval_svc = RetrievalService(
        embedding_service=embedding_svc,
        vector_store=vector_store,
        hybrid_enabled=getattr(settings, "HYBRID_SEARCH_ENABLED", False),
        score_threshold=getattr(settings, "RETRIEVAL_SCORE_THRESHOLD", 0.0),
    )

    visibility_filter = build_visibility_filter(user)

    try:
        chunks = await retrieval_svc.retrieve(
            query_text=search_query,
            filter=visibility_filter,
            top_k=10,
        )
    except Exception as exc:
        logger.warning("Agenda retrieval failed (non-fatal): %s", exc)
        chunks = []

    # Summarise retrieved docs for the prompt
    doc_summaries_parts: list[str] = []
    seen_docs: set[str] = set()
    sources: list[dict] = []

    for chunk in chunks:
        doc_id = chunk.document_id
        filename = chunk.metadata.get("filename", "unknown")
        if doc_id not in seen_docs:
            seen_docs.add(doc_id)
            sources.append({"document_id": doc_id, "filename": filename})
        doc_summaries_parts.append(f"- [{filename}]: {chunk.text[:400]}")

    doc_summaries = "\n".join(doc_summaries_parts) if doc_summaries_parts else "No relevant documents found."

    event_date_str = ev.start_time.strftime("%A, %B %d, %Y at %I:%M %p UTC")

    agenda_prompt = (
        f"Generate a structured meeting agenda for: '{ev.title}' "
        f"scheduled on {event_date_str}.\n\n"
        f"Relevant background documents:\n{doc_summaries}\n\n"
        "Create:\n"
        "1) Objectives\n"
        "2) Agenda items with time estimates\n"
        "3) Pre-reading links / document references\n"
        "4) Expected outcomes\n\n"
        f"Context: {context or 'None provided'}"
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are Nexus, a helpful enterprise AI assistant. "
                "Generate a clear, structured meeting agenda in markdown format."
            ),
        },
        {"role": "user", "content": agenda_prompt},
    ]

    import asyncio
    from src.core.interfaces import LLMResponse
    from src.llm import get_llm

    llm = get_llm(settings)
    try:
        response: LLMResponse = await asyncio.wait_for(
            llm.generate(messages, temperature=0.3),
            timeout=90.0,
        )
        agenda_text = (response.content or "").strip()
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM request timed out while generating agenda.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Agenda generation failed: {exc}",
        )

    # Persist agenda on the event
    ev.agenda = agenda_text
    await db.commit()

    return {
        "agenda":             agenda_text,
        "relevant_doc_count": len(seen_docs),
        "sources":            sources,
    }


@router.get("/events/{event_id}/agenda")
async def get_agenda(
    event_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the stored AI-generated agenda for an event, or 404 if not yet generated."""
    ev = (await db.execute(
        select(CalendarEvent).where(CalendarEvent.id == event_id)
    )).scalar_one_or_none()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")

    is_involved = ev.created_by == user.user_id or any(
        a.user_id == user.user_id for a in ev.attendees
    )
    if not is_involved:
        raise HTTPException(status_code=403, detail="Access denied")

    if not ev.agenda:
        raise HTTPException(status_code=404, detail="No agenda generated for this event yet")

    await db.commit()
    return {"agenda": ev.agenda}


@router.post("/import")
async def import_calendar_ics(
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import events from an uploaded .ics file."""
    from src.repositories.user_repository import UserRepository
    repo = UserRepository(db)
    db_user = await repo.get_by_id(user.user_id)
    creator_username = db_user.username if db_user else user.user_id

    try:
        from icalendar import Calendar as ICalCalendar
    except ImportError:
        raise HTTPException(status_code=500, detail="icalendar library not installed")

    content = await file.read()
    try:
        cal = ICalCalendar.from_ical(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid iCal file: {exc}")

    imported = 0
    failed = 0
    errors: list[str] = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        try:
            summary = str(component.get("summary", "Imported Event"))
            dtstart = component.get("dtstart")
            dtend = component.get("dtend")

            if dtstart is None:
                raise ValueError("DTSTART is missing")
            if dtend is None:
                raise ValueError("DTEND is missing")

            # dt values may be date or datetime
            def _to_dt(val) -> datetime:
                if isinstance(val.dt, datetime):
                    return val.dt if val.dt.tzinfo else val.dt.replace(tzinfo=timezone.utc)
                # date only — convert to midnight UTC
                from datetime import date as ddate
                if isinstance(val.dt, ddate):
                    return datetime(val.dt.year, val.dt.month, val.dt.day, tzinfo=timezone.utc)
                raise ValueError(f"Unexpected date type: {type(val.dt)}")

            start_time = _to_dt(dtstart)
            end_time = _to_dt(dtend)

            description_raw = component.get("description")
            description = str(description_raw) if description_raw else None
            location_raw = component.get("location")
            location = str(location_raw) if location_raw else None

            # Use the UID from the iCal if it is a valid UUID, otherwise generate new
            uid_raw = str(component.get("uid", ""))
            try:
                event_id = str(uuid.UUID(uid_raw))
            except (ValueError, AttributeError):
                event_id = str(uuid.uuid4())

            ev = CalendarEvent(
                id=event_id,
                title=summary,
                description=description,
                location=location,
                start_time=start_time,
                end_time=end_time,
                created_by=user.user_id,
                creator_username=creator_username,
                recurrence_parent_id=None,
                is_cancelled=False,
                reminder_sent=False,
            )
            db.add(ev)
            await db.flush()
            db.add(EventAttendee(
                event_id=ev.id,
                user_id=user.user_id,
                username=creator_username,
                status="accepted",
            ))
            await db.flush()
            imported += 1
        except Exception as exc:
            failed += 1
            errors.append(str(exc))

    await db.commit()
    return {"imported": imported, "failed": failed, "errors": errors}
