"""Notification endpoints + per-user WebSocket."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db
from src.config import get_settings
from src.core.rbac import UserContext
from src.core.security import decode_access_token
from src.models.notification import Notification
from src.services.notification_manager import notif_manager
from src.services.presence_service import presence_service, VALID_STATUSES

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str | None
    link: str | None
    is_read: bool
    created_at: datetime


class SetStatusRequest(BaseModel):
    status: str
    custom_status: str | None = None


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, type=n.type, title=n.title, body=n.body,
        link=n.link, is_read=n.is_read, created_at=n.created_at,
    )


# ── REST ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    limit: int = Query(30, le=100),
    unread_only: bool = False,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)  # noqa: E712
    result = await db.execute(stmt)
    notifs = list(result.scalars().all())
    await db.commit()
    return [_out(n) for n in notifs]


@router.get("/unread-count")
async def unread_count(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    result = await db.execute(
        select(func.count()).where(
            Notification.user_id == user.user_id,
            Notification.is_read == False,  # noqa: E712
        )
    )
    count = result.scalar_one()
    await db.commit()
    return {"count": count}


@router.patch("/{notification_id}/read")
async def mark_one_read(
    notification_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.user_id)
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}


@router.patch("/read-all")
async def mark_all_read(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.user_id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )
    await db.commit()
    return {"ok": True}


# ── Feature 5: Set custom status ──────────────────────────────────────────────

@router.patch("/status")
async def set_status(
    body: SetStatusRequest,
    user: UserContext = Depends(get_current_user),
):
    """Feature 5: PATCH /notifications/status — update presence status and broadcast to all."""
    if body.status not in VALID_STATUSES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(VALID_STATUSES)}")

    presence_service.set_status(user.user_id, body.status, body.custom_status)

    # Broadcast presence update to all connected chat WebSocket clients
    from src.services.chat_manager import manager
    await manager.broadcast_all({
        "type": "presence_update",
        "user_id": user.user_id,
        "status": body.status,
        "custom_status": body.custom_status,
    })

    return {"ok": True, "status": body.status, "custom_status": body.custom_status}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def notifications_ws(
    websocket: WebSocket,
    token: str = Query(...),
):
    """Connect with ?token=<access_token> to receive real-time notifications.

    Feature 5: connecting sets user online; disconnecting sets user offline.
    Clients should send {"type": "ping"} every 30s; server replies {"type": "pong"}.
    """
    settings = get_settings()
    try:
        payload = decode_access_token(token, settings.APP_SECRET_KEY, settings.JWT_ALGORITHM)
    except Exception:
        await websocket.close(code=4001)
        return

    user_id = payload["sub"]
    username = payload.get("username", "")

    await notif_manager.connect(websocket, user_id)

    # Feature 5: mark online and broadcast
    presence_service.set_online(user_id, username)
    from src.services.chat_manager import manager as chat_manager
    await chat_manager.broadcast_all({
        "type": "presence_update",
        "user_id": user_id,
        "status": "online",
        "custom_status": presence_service.get(user_id).get("custom_status"),
    })

    try:
        while True:
            raw = await websocket.receive_text()
            # Support JSON ping from client
            try:
                import json
                data = json.loads(raw)
                if data.get("type") == "ping":
                    presence_service.record_ping(user_id)
                    await websocket.send_text('{"type": "pong"}')
            except Exception:
                pass  # plain text ping or unknown — ignore
    except WebSocketDisconnect:
        notif_manager.disconnect(websocket, user_id)

        # Feature 5: mark offline only if no other notification sockets remain
        if not notif_manager._connections.get(user_id):
            presence_service.set_offline(user_id)
            await chat_manager.broadcast_all({
                "type": "presence_update",
                "user_id": user_id,
                "status": "offline",
                "custom_status": presence_service.get(user_id).get("custom_status"),
            })
