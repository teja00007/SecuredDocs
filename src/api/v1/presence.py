"""Feature 5: User presence / status endpoint.

Registers under /auth prefix so PATCH /auth/status works as specified.
Does NOT modify src/api/v1/auth.py (protected file).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.v1.deps import get_current_user
from src.core.rbac import UserContext
from src.services.presence_service import presence_service, VALID_STATUSES

router = APIRouter(prefix="/auth", tags=["presence"])


class SetStatusRequest(BaseModel):
    status: str
    custom_status: str | None = None


@router.patch("/status")
async def set_user_status(
    body: SetStatusRequest,
    user: UserContext = Depends(get_current_user),
):
    """Feature 5: Update the authenticated user's presence status and broadcast to all.

    Body: {"status": "online"|"away"|"dnd"|"offline", "custom_status": "In a meeting"}
    """
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(VALID_STATUSES)}",
        )

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
