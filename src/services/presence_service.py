"""Feature 5: In-memory user presence tracking.

Presence resets on server restart — that is intentional for a real-time status indicator.
Format: {user_id: {"status": "online"|"away"|"offline", "last_seen": datetime, "custom_status": str|None}}
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Valid status values
VALID_STATUSES = {"online", "away", "dnd", "offline"}

# If no ping received within this many seconds, mark user as "away"
AWAY_TIMEOUT_SECONDS = 60


class PresenceService:
    def __init__(self) -> None:
        self._presence: dict[str, dict] = {}
        # track last ping time separately
        self._last_ping: dict[str, datetime] = {}

    def set_online(self, user_id: str, username: str = "") -> None:
        """Called when a user connects to any WebSocket."""
        now = datetime.now(timezone.utc)
        existing = self._presence.get(user_id, {})
        self._presence[user_id] = {
            "status": "online",
            "last_seen": now,
            "custom_status": existing.get("custom_status"),
            "username": username or existing.get("username", ""),
        }
        self._last_ping[user_id] = now

    def set_offline(self, user_id: str) -> None:
        """Called when a user disconnects from all WebSockets."""
        now = datetime.now(timezone.utc)
        existing = self._presence.get(user_id, {})
        self._presence[user_id] = {
            "status": "offline",
            "last_seen": now,
            "custom_status": existing.get("custom_status"),
            "username": existing.get("username", ""),
        }
        self._last_ping.pop(user_id, None)

    def record_ping(self, user_id: str) -> None:
        """Called when a user sends a heartbeat ping."""
        self._last_ping[user_id] = datetime.now(timezone.utc)
        if self._presence.get(user_id, {}).get("status") == "away":
            p = self._presence[user_id]
            p["status"] = "online"
            p["last_seen"] = datetime.now(timezone.utc)

    def set_status(self, user_id: str, status: str, custom_status: str | None = None) -> dict:
        """Manually update status and custom_status. Returns updated presence dict."""
        now = datetime.now(timezone.utc)
        existing = self._presence.get(user_id, {})
        self._presence[user_id] = {
            "status": status,
            "last_seen": now,
            "custom_status": custom_status,
            "username": existing.get("username", ""),
        }
        return self._presence[user_id]

    def get(self, user_id: str) -> dict:
        return self._presence.get(user_id, {
            "status": "offline",
            "last_seen": None,
            "custom_status": None,
            "username": "",
        })

    def get_all(self) -> dict[str, dict]:
        return dict(self._presence)

    def check_away_timeouts(self) -> list[str]:
        """Check all online users and mark as 'away' if no ping within AWAY_TIMEOUT_SECONDS.
        Returns list of user_ids that were changed to away.
        """
        now = datetime.now(timezone.utc)
        changed: list[str] = []
        for user_id, p in self._presence.items():
            if p.get("status") == "online":
                last_ping = self._last_ping.get(user_id)
                if last_ping is None:
                    continue
                delta = (now - last_ping).total_seconds()
                if delta > AWAY_TIMEOUT_SECONDS:
                    p["status"] = "away"
                    p["last_seen"] = now
                    changed.append(user_id)
        return changed


# Module-level singleton
presence_service = PresenceService()
