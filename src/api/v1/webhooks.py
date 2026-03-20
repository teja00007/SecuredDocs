"""Outbound webhook management endpoints.

All routes require the admin role.

# ── To wire into __init__.py ───────────────────────────────────────────────────
# from src.api.v1.webhooks import router as webhooks_router
# api_router.include_router(webhooks_router)
# ──────────────────────────────────────────────────────────────────────────────
"""

import json
import secrets
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_db, get_current_user
from src.core.rbac import UserContext
from src.models.webhook import Webhook

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── Auth helper ───────────────────────────────────────────────────────────────

def _require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    if "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


# ── Schemas ───────────────────────────────────────────────────────────────────

_VALID_EVENTS = {
    "document.uploaded",
    "document.ingested",
    "query.completed",
    "user.created",
    "message.sent",
    "calendar.event.created",
}


class WebhookCreateRequest(BaseModel):
    name: str
    url: str
    events: list[str]


class WebhookResponse(BaseModel):
    id: str
    name: str
    url: str
    events: list[str]
    is_active: bool
    owner_id: str
    last_triggered_at: datetime | None
    last_status_code: int | None
    created_at: datetime
    # Secret is only returned at creation time — set to None otherwise.
    secret: str | None = None

    model_config = {"from_attributes": True}


def _to_response(webhook: Webhook, include_secret: bool = False) -> WebhookResponse:
    try:
        events = json.loads(webhook.events or "[]")
    except Exception:
        events = []
    return WebhookResponse(
        id=webhook.id,
        name=webhook.name,
        url=webhook.url,
        events=events,
        is_active=webhook.is_active,
        owner_id=webhook.owner_id,
        last_triggered_at=webhook.last_triggered_at,
        last_status_code=webhook.last_status_code,
        created_at=webhook.created_at,
        secret=webhook.secret if include_secret else None,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_https_url(url: str) -> None:
    if not url.startswith("https://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook URL must start with https://",
        )


def _validate_events(events: list[str]) -> None:
    invalid = [e for e in events if e not in _VALID_EVENTS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown event type(s): {invalid}. Valid types: {sorted(_VALID_EVENTS)}",
        )
    if not events:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one event type must be specified",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreateRequest,
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new outbound webhook. The secret is shown ONCE in the response."""
    _validate_https_url(body.url)
    _validate_events(body.events)

    secret = secrets.token_hex(32)
    webhook = Webhook(
        id=str(uuid.uuid4()),
        name=body.name,
        url=body.url,
        secret=secret,
        events=json.dumps(body.events),
        is_active=True,
        owner_id=admin.user_id,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return _to_response(webhook, include_secret=True)


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all registered webhooks. Secrets are NOT returned."""
    result = await db.execute(select(Webhook).order_by(Webhook.created_at.desc()))
    webhooks = result.scalars().all()
    await db.commit()
    return [_to_response(w) for w in webhooks]


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: str,
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook."""
    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    await db.delete(webhook)
    await db.commit()


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: str,
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Send a test event to the webhook URL and return the delivery result."""
    import hashlib
    import hmac as hmac_mod

    result = await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")

    now = datetime.now(timezone.utc)
    test_payload = {
        "event": "test",
        "timestamp": now.isoformat(),
        "data": {"message": "This is a test event from Nexus", "webhook_id": webhook_id},
    }
    import json as _json
    body_bytes = _json.dumps(test_payload, default=str).encode("utf-8")

    sig = hmac_mod.new(
        webhook.secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Nexus-Event": "test",
        "X-Nexus-Signature": f"sha256={sig}",
    }

    success = False
    status_code = None
    response_body = ""
    error_detail = None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook.url, content=body_bytes, headers=headers)
            status_code = resp.status_code
            response_body = resp.text[:500]
            success = resp.status_code < 400
    except Exception as exc:
        error_detail = str(exc)

    # Update tracking columns
    webhook.last_triggered_at = now
    webhook.last_status_code = status_code
    await db.commit()

    return {
        "status_code": status_code,
        "success": success,
        "response_body": response_body,
        "error": error_detail,
    }
