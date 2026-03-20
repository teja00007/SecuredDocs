"""WebSocket manager for real-time per-user notifications."""

import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class NotificationManager:
    """One WebSocket connection per user (multiple tabs allowed)."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        await websocket.accept()
        self._connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        self._connections[user_id] = [
            ws for ws in self._connections[user_id] if ws is not websocket
        ]

    async def push(self, user_id: str, payload: dict) -> None:
        """Push a notification to all open tabs for this user."""
        if not self._connections.get(user_id):
            return
        text = json.dumps(payload)
        dead: list[WebSocket] = []
        for ws in self._connections[user_id]:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, user_id)

    async def push_many(self, user_ids: list[str], payload: dict) -> None:
        for uid in user_ids:
            await self.push(uid, payload)


# Module-level singleton
notif_manager = NotificationManager()
