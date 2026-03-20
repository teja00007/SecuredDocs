"""Invite-management endpoints (admin only)."""

import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db, require_permission
from src.core.rbac import UserContext
from src.models.invite import Invite
from src.models.user import User
from src.schemas.auth import InviteCreateRequest, InviteResponse, InviteValidateResponse
from src.services.email_service import EmailService

router = APIRouter(prefix="/invites", tags=["invites"])


def _build_invite_response(invite: Invite) -> InviteResponse:
    return InviteResponse(
        invite_id=invite.id,
        token=invite.token,
        email=invite.email,
        roles=json.loads(invite.roles),
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        accepted_at=invite.accepted_at,
    )


# ---------------------------------------------------------------------------
# POST /invites — create an invite (admin only)
# ---------------------------------------------------------------------------

@router.post("", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    body: InviteCreateRequest,
    current_user: UserContext = Depends(require_permission("admin:write")),
    db: AsyncSession = Depends(get_db),
):
    # Check email not already registered
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{body.email}' is already registered",
        )

    # Check no pending (not accepted, not expired) invite for this email
    result = await db.execute(
        select(Invite).where(
            Invite.email == body.email,
            Invite.accepted_at.is_(None),
            Invite.expires_at > datetime.now(timezone.utc),
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A pending invite for '{body.email}' already exists",
        )

    token = secrets.token_hex(32)
    invite = Invite(
        token=token,
        email=body.email,
        invited_by_id=current_user.user_id,
        roles=json.dumps(body.roles),
        team_ids=json.dumps(body.team_ids),
    )
    db.add(invite)
    await db.flush()
    await db.refresh(invite)

    # Fetch inviter's username for the email
    inviter_result = await db.execute(select(User).where(User.id == current_user.user_id))
    inviter = inviter_result.scalar_one_or_none()
    invited_by_name = inviter.username if inviter else "Nexus Admin"

    await db.commit()

    # Send invite email
    email_svc = EmailService()
    try:
        await email_svc.send_invite(
            to_email=body.email,
            invite_token=token,
            invited_by=invited_by_name,
            org_name="Nexus",
        )
    except Exception:
        pass  # Don't fail the request if email is not configured

    return _build_invite_response(invite)


# ---------------------------------------------------------------------------
# GET /invites — list pending invites (admin only)
# ---------------------------------------------------------------------------

@router.get("", response_model=list[InviteResponse])
async def list_invites(
    current_user: UserContext = Depends(require_permission("admin:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invite).where(
            Invite.accepted_at.is_(None),
            Invite.expires_at > datetime.now(timezone.utc),
        )
    )
    invites = result.scalars().all()
    return [_build_invite_response(i) for i in invites]


# ---------------------------------------------------------------------------
# DELETE /invites/{invite_id} — revoke an invite (admin only)
# ---------------------------------------------------------------------------

@router.delete("/{invite_id}", status_code=status.HTTP_200_OK)
async def revoke_invite(
    invite_id: str,
    current_user: UserContext = Depends(require_permission("admin:write")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Invite).where(Invite.id == invite_id))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    await db.delete(invite)
    await db.commit()
    return {"message": "Invite revoked"}


# ---------------------------------------------------------------------------
# GET /invites/validate/{token} — public token validation
# ---------------------------------------------------------------------------

@router.get("/validate/{token}", response_model=InviteValidateResponse)
async def validate_invite(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Invite).where(Invite.token == token))
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    if invite.accepted_at is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite already accepted")

    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite has expired")

    return InviteValidateResponse(
        email=invite.email,
        valid=True,
        expires_at=invite.expires_at,
    )
