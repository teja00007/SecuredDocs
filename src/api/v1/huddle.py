"""Livekit huddle — generate join tokens, direct calls, and channel calls."""

import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db
from src.config import get_settings
from src.core.rbac import UserContext
from src.models.notification import Notification
from src.models.chat import Channel, ChannelMember
from src.services.notification_service import create_and_push

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/huddle", tags=["huddle"])

# Pending notifications held until the caller actually joins the LiveKit room.
# Keyed by room_name → (created_timestamp, list of notification dicts).
_pending_notifications: dict[str, tuple[float, list[dict]]] = {}


# ── Schemas ────────────────────────────────────────────────────────────────────

class IceServer(BaseModel):
    urls: str
    username: str = ""
    credential: str = ""

class JoinToken(BaseModel):
    room_name: str
    token: str
    ws_url: str
    ice_servers: list[IceServer] = []
    ice_transport_policy: str = "all"

class DirectCallRequest(BaseModel):
    target_user_id: str
    target_username: str

class ChannelCallRequest(BaseModel):
    channel_id: str


# ── Token helper ───────────────────────────────────────────────────────────────

def _build_livekit_token(room_name: str, user_id: str, username: str, api_key: str, api_secret: str) -> str:
    try:
        from livekit.api import AccessToken, VideoGrants  # type: ignore
        token = (
            AccessToken(api_key, api_secret)
            .with_identity(user_id)
            .with_name(username)
            .with_grants(VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )
        return token
    except ImportError:
        import base64, json
        payload = json.dumps({"sub": user_id, "name": username, "room": room_name, "exp": int(time.time()) + 3600})
        return base64.b64encode(payload.encode()).decode()

def _resolve_ws_url(ws_url: str, request: Request) -> str:
    """Replace localhost in ws_url with the request's Host when the caller is
    reaching the API via a LAN/public IP.  This ensures the browser connects
    to the LiveKit server on the same host it used for the API."""
    parsed = urlparse(ws_url)
    if parsed.hostname not in ("localhost", "127.0.0.1"):
        return ws_url
    req_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0]
    if req_host and req_host not in ("localhost", "127.0.0.1"):
        return f"{parsed.scheme}://{req_host}:{parsed.port or 7880}"
    return ws_url

def _build_ice_servers(settings, request: Request) -> tuple[list[IceServer], str]:
    """Return (ice_servers, ice_transport_policy) from settings.
    If TURN_URL is set, the TURN host is also resolved against the request host
    so that 'localhost' in TURN_URL is replaced with the caller's IP."""
    turn_url   = getattr(settings, "TURN_URL", "")
    turn_user  = getattr(settings, "TURN_USERNAME", "")
    turn_cred  = getattr(settings, "TURN_CREDENTIAL", "")
    policy     = getattr(settings, "ICE_TRANSPORT_POLICY", "all")

    if not turn_url:
        return [], "all"

    # Apply the same localhost→caller-IP resolution as ws_url
    from urllib.parse import urlparse
    parsed = urlparse(turn_url.split("?")[0].replace("turn:", "http://"))
    if parsed.hostname in ("localhost", "127.0.0.1"):
        req_host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(":")[0]
        if req_host and req_host not in ("localhost", "127.0.0.1"):
            turn_url = turn_url.replace(parsed.hostname, req_host)

    return [IceServer(urls=turn_url, username=turn_user, credential=turn_cred)], policy

def _make_token(room_name: str, user: UserContext, request: Request) -> JoinToken:
    settings = get_settings()
    api_key    = getattr(settings, "LIVEKIT_API_KEY", "")
    api_secret = getattr(settings, "LIVEKIT_API_SECRET", "")
    ws_url     = getattr(settings, "LIVEKIT_URL", "ws://localhost:7880")
    ws_url     = _resolve_ws_url(ws_url, request)
    ice_servers, ice_policy = _build_ice_servers(settings, request)
    if not api_key:
        return JoinToken(room_name=room_name, token="dev-token", ws_url=ws_url,
                         ice_servers=ice_servers, ice_transport_policy=ice_policy)
    token = _build_livekit_token(room_name, user.user_id, user.username or user.user_id, api_key, api_secret)
    return JoinToken(room_name=room_name, token=token, ws_url=ws_url,
                     ice_servers=ice_servers, ice_transport_policy=ice_policy)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/rooms/{room_name}/join", response_model=JoinToken)
async def join_room(
    room_name: str,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """Return a Livekit JWT so the frontend can connect to the room."""
    return _make_token(room_name, user, request)


@router.post("/rooms/instant", response_model=JoinToken)
async def instant_room(request: Request, user: UserContext = Depends(get_current_user)):
    """Create an ad-hoc room (huddle) and return a join token."""
    return _make_token(f"huddle-{secrets.token_urlsafe(6)}", user, request)


@router.post("/rooms/direct-call", response_model=JoinToken)
async def direct_call(
    body: DirectCallRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
):
    """Start a 1-to-1 video call.  Notification is deferred until the caller
    actually joins the LiveKit room (POST /rooms/{room}/started)."""
    room_name = f"call-{secrets.token_urlsafe(8)}"

    _pending_notifications[room_name] = (time.time(), [{
        "user_id": body.target_user_id,
        "type": "incoming_call",
        "title": f"{user.username or 'Someone'} is calling you",
        "body": f"Incoming video call from {user.username}",
        "link": f"/huddle/{room_name}",
    }])

    return _make_token(room_name, user, request)


@router.post("/rooms/channel-call", response_model=JoinToken)
async def channel_call(
    body: ChannelCallRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a group/channel call.  Notifications are deferred until the caller
    actually joins the LiveKit room (POST /rooms/{room}/started)."""
    room_name = f"meet-{secrets.token_urlsafe(8)}"

    # Resolve channel name
    ch_res = await db.execute(select(Channel.name, Channel.type).where(Channel.id == body.channel_id))
    ch_row = ch_res.first()
    ch_label = ch_row[0] if ch_row else "channel"

    # Collect notifications for all members except caller
    pending: list[dict] = []
    mem_res = await db.execute(
        select(ChannelMember.user_id).where(ChannelMember.channel_id == body.channel_id)
    )
    for (member_uid,) in mem_res.all():
        if member_uid == user.user_id:
            continue
        pending.append({
            "user_id": member_uid,
            "type": "meeting_started",
            "title": f"Meeting started in #{ch_label}",
            "body": f"{user.username or 'Someone'} started a video call. Join now.",
            "link": f"/huddle/{room_name}",
        })

    _pending_notifications[room_name] = (time.time(), pending)
    return _make_token(room_name, user, request)


@router.post("/rooms/{room_name}/started")
async def room_started(
    room_name: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Called by frontend after the caller connects to LiveKit.
    Sends any pending call/meeting notifications for this room."""
    entry = _pending_notifications.pop(room_name, None)
    sent = 0
    if entry:
        _, notifications = entry
        for n in notifications:
            await create_and_push(db, n["user_id"], n["type"], n["title"], n.get("body"), n.get("link"))
        await db.commit()
        sent = len(notifications)

    # Housekeeping: drop stale pending entries (caller never joined)
    now = time.time()
    stale = [k for k, (ts, _) in _pending_notifications.items() if now - ts > 300]
    for k in stale:
        del _pending_notifications[k]

    return {"ok": True, "notified": sent}


@router.get("/pending-calls")
async def pending_calls(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return unread incoming_call notifications younger than 60 s (for ringing overlay)."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user.user_id)
        .where(Notification.type == "incoming_call")
        .where(Notification.is_read == False)  # noqa: E712
        .where(Notification.created_at >= cutoff)
        .order_by(Notification.created_at.desc())
    )
    return result.scalars().all()


@router.post("/pending-calls/{notif_id}/dismiss")
async def dismiss_call(
    notif_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an incoming_call notification as read (decline or after joining)."""
    result = await db.execute(
        select(Notification)
        .where(Notification.id == notif_id)
        .where(Notification.user_id == user.user_id)
    )
    notif = result.scalar_one_or_none()
    if notif:
        notif.is_read = True
        await db.commit()
    return {"ok": True}
