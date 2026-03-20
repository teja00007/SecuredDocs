"""API Key management endpoints.

Allows authenticated users to create, list, and revoke long-lived API keys
that can be used as Bearer tokens in place of JWT access tokens on supported
endpoints.

Key format: nxs_<48 random base64url chars>  (~52 chars total)
Storage:    sha256(key) hex digest — plaintext is never stored.
"""

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db
from src.core.rbac import UserContext
from src.models.api_key import APIKey

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

VALID_SCOPES = frozenset(["query", "documents:read", "documents:write"])


class APIKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, description="Human-readable label")
    scopes: list[str] = Field(default=["query"], description="List of permission scopes")
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Days until expiry; null = never expires",
    )


class APIKeyCreateResponse(BaseModel):
    id: str
    name: str
    key: str  # Shown ONCE — the full raw key
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    created_at: datetime


class APIKeyListItem(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: list[str]
    last_used_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_api_key() -> str:
    """Generate a new API key in the format: nxs_<48 random base64url chars>."""
    return "nxs_" + secrets.token_urlsafe(36)


def _validate_scopes(scopes: list[str]) -> None:
    invalid = set(scopes) - VALID_SCOPES
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope(s): {sorted(invalid)}. Valid scopes: {sorted(VALID_SCOPES)}",
        )


# ---------------------------------------------------------------------------
# POST /api-keys — create a new key
# ---------------------------------------------------------------------------

@router.post("", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: APIKeyCreateRequest,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key. The full key is returned once and is never shown again."""
    _validate_scopes(body.scopes)

    raw_key = _generate_api_key()
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:8]  # "nxs_a1b2" — first 8 chars

    expires_at: datetime | None = None
    if body.expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)

    api_key = APIKey(
        id=str(uuid.uuid4()),
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        user_id=current_user.user_id,
        scopes=json.dumps(body.scopes),
        expires_at=expires_at,
        is_active=True,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key=raw_key,
        key_prefix=api_key.key_prefix,
        scopes=json.loads(api_key.scopes),
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api-keys — list user's keys (no plaintext key ever returned)
# ---------------------------------------------------------------------------

@router.get("", response_model=list[APIKeyListItem])
async def list_api_keys(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == current_user.user_id)
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        APIKeyListItem(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=json.loads(k.scopes),
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            is_active=k.is_active,
            created_at=k.created_at,
        )
        for k in keys
    ]


# ---------------------------------------------------------------------------
# DELETE /api-keys/{key_id} — deactivate a key
# ---------------------------------------------------------------------------

@router.delete("/{key_id}", status_code=status.HTTP_200_OK)
async def revoke_api_key(
    key_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.user_id == current_user.user_id,
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    api_key.is_active = False
    await db.commit()
    return {"message": "API key revoked"}
