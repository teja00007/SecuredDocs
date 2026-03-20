"""Redis-backed sliding window conversation memory per session.

Stores the last N turns (user + assistant) per session_id.
Automatically expires after TTL seconds of inactivity.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_KEY_PREFIX = "conv:"


class ConversationMemory:
    """Redis-backed sliding window conversation history."""

    def __init__(
        self,
        redis_client,
        window_size: int = 6,
        ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis_client
        self._window = window_size
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"{_KEY_PREFIX}{session_id}"

    async def get_history(self, session_id: str) -> list[dict]:
        """Return the last window_size messages for this session."""
        try:
            raw = await self._redis.get(self._key(session_id))
            if raw:
                history: list[dict] = json.loads(raw)
                return history[-self._window :]
        except Exception as exc:
            logger.debug("ConversationMemory.get_history failed (non-fatal): %s", exc)
        return []

    async def add_turn(
        self, session_id: str, user_msg: str, assistant_msg: str
    ) -> None:
        """Append a user+assistant turn and trim to window."""
        try:
            history = await self.get_history(session_id)
            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": assistant_msg})
            history = history[-self._window :]
            await self._redis.setex(
                self._key(session_id), self._ttl, json.dumps(history)
            )
        except Exception as exc:
            logger.debug("ConversationMemory.add_turn failed (non-fatal): %s", exc)

    async def clear(self, session_id: str) -> None:
        """Clear history for a session."""
        try:
            await self._redis.delete(self._key(session_id))
        except Exception as exc:
            logger.debug("ConversationMemory.clear failed (non-fatal): %s", exc)
