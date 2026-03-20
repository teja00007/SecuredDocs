"""Helper to create a notification in DB and push it via WebSocket."""

import uuid
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.notification import Notification
from src.services.notification_manager import notif_manager

logger = logging.getLogger(__name__)


async def create_and_push(
    db: AsyncSession,
    user_id: str,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> None:
    """Persist a notification and push it over WebSocket (fire-and-forget safe)."""
    try:
        notif = Notification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
        )
        db.add(notif)
        await db.flush()

        await notif_manager.push(user_id, {
            "type": "notification",
            "id": notif.id,
            "notif_type": type,
            "title": title,
            "body": body,
            "link": link,
            "is_read": False,
            "created_at": notif.created_at.isoformat(),
        })
    except Exception as e:
        logger.warning("Failed to create notification for user %s: %s", user_id, e)
