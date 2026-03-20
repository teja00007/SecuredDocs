"""Outbound webhook delivery service.

Finds all active webhooks subscribed to a given event type and POSTs
a signed JSON payload to each registered URL.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.webhook import Webhook

logger = logging.getLogger(__name__)


class WebhookService:
    async def trigger(
        self,
        event_type: str,
        payload: dict,
        db: AsyncSession,
    ) -> None:
        """Find all active webhooks subscribed to *event_type* and deliver the event.

        This method never raises — failures are logged at WARNING level so that
        callers (ingestion pipeline, upload handler, etc.) are never crashed by a
        broken or unreachable webhook endpoint.
        """
        try:
            result = await db.execute(
                select(Webhook).where(Webhook.is_active == True)  # noqa: E712
            )
            webhooks = result.scalars().all()
        except Exception as exc:
            logger.warning("WebhookService: could not query webhooks — %s", exc)
            return

        if not webhooks:
            return

        now = datetime.now(timezone.utc)
        envelope = {
            "event": event_type,
            "timestamp": now.isoformat(),
            "data": payload,
        }
        json_body = json.dumps(envelope, default=str)
        body_bytes = json_body.encode("utf-8")

        async with httpx.AsyncClient(timeout=10) as client:
            for webhook in webhooks:
                # Check this webhook subscribes to the event
                try:
                    subscribed = json.loads(webhook.events or "[]")
                except Exception:
                    subscribed = []

                if event_type not in subscribed:
                    continue

                # Compute HMAC-SHA256 signature
                try:
                    sig = hmac.new(
                        webhook.secret.encode("utf-8"),
                        body_bytes,
                        hashlib.sha256,
                    ).hexdigest()
                except Exception as exc:
                    logger.warning(
                        "WebhookService: could not compute signature for webhook %s — %s",
                        webhook.id,
                        exc,
                    )
                    continue

                headers = {
                    "Content-Type": "application/json",
                    "X-Nexus-Event": event_type,
                    "X-Nexus-Signature": f"sha256={sig}",
                }

                status_code: int | None = None
                try:
                    response = await client.post(webhook.url, content=body_bytes, headers=headers)
                    status_code = response.status_code
                    if response.status_code >= 400:
                        logger.warning(
                            "WebhookService: delivery to %s returned HTTP %d",
                            webhook.url,
                            response.status_code,
                        )
                except Exception as exc:
                    logger.warning(
                        "WebhookService: delivery to %s failed — %s", webhook.url, exc
                    )

                # Update tracking columns (best-effort — don't crash on DB errors)
                try:
                    webhook.last_triggered_at = now
                    webhook.last_status_code = status_code
                    await db.flush()
                except Exception as exc:
                    logger.warning(
                        "WebhookService: could not update tracking for webhook %s — %s",
                        webhook.id,
                        exc,
                    )
