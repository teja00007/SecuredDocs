"""WebSocket connection manager for real-time chat."""

import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks active WebSocket connections per channel."""

    def __init__(self) -> None:
        # channel_id → list of (websocket, user_id, username)
        self._connections: dict[str, list[tuple[WebSocket, str, str]]] = defaultdict(list)
        # All connected websockets keyed by user_id (for global presence broadcasts)
        self._user_sockets: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, channel_id: str, user_id: str, username: str) -> None:
        await websocket.accept()
        self._connections[channel_id].append((websocket, user_id, username))
        self._user_sockets[user_id].append(websocket)
        logger.debug("WS connected: user=%s channel=%s", username, channel_id)

    def disconnect(self, websocket: WebSocket, channel_id: str) -> None:
        entry = next(
            ((ws, uid, uname) for ws, uid, uname in self._connections[channel_id] if ws is websocket),
            None,
        )
        self._connections[channel_id] = [
            (ws, uid, uname)
            for ws, uid, uname in self._connections[channel_id]
            if ws is not websocket
        ]
        if entry:
            uid = entry[1]
            self._user_sockets[uid] = [ws for ws in self._user_sockets[uid] if ws is not websocket]

    async def broadcast(self, channel_id: str, message: dict) -> None:
        """Send a JSON message to all connections in a channel."""
        payload = json.dumps(message)
        dead: list[WebSocket] = []
        for ws, _, _ in self._connections.get(channel_id, []):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel_id)

    async def broadcast_all(self, message: dict) -> None:
        """Send a JSON message to every connected WebSocket across all channels."""
        payload = json.dumps(message)
        dead: list[tuple[WebSocket, str]] = []
        seen: set[int] = set()  # avoid duplicate sends on multi-channel connections
        for channel_id, conns in list(self._connections.items()):
            for ws, uid, _ in conns:
                if id(ws) in seen:
                    continue
                seen.add(id(ws))
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append((ws, channel_id))
        for ws, channel_id in dead:
            self.disconnect(ws, channel_id)

    def online_users(self, channel_id: str) -> list[str]:
        return [uname for _, _, uname in self._connections.get(channel_id, [])]

    def online_user_ids(self, channel_id: str) -> set[str]:
        return {uid for _, uid, _ in self._connections.get(channel_id, [])}

    def is_user_connected(self, user_id: str) -> bool:
        """Return True if the user has at least one active WebSocket."""
        return bool(self._user_sockets.get(user_id))

    def all_connected_user_ids(self) -> set[str]:
        return {uid for uid, sockets in self._user_sockets.items() if sockets}


# Module-level singleton shared across all requests
manager = ConnectionManager()
