"""Connector management endpoints — external document source integration.

=============================================================================
INTEGRATION INSTRUCTIONS
=============================================================================

1. src/api/v1/__init__.py — add the following two lines in the same style as
   the other routers:

       from src.api.v1.connectors import router as connectors_router
       v1_router.include_router(connectors_router)

2. src/main.py — no changes required; the router is registered via __init__.py.

=============================================================================
"""

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db
from src.core.rbac import UserContext
from src.models.connector import Connector, ConnectorDocument

router = APIRouter(prefix="/connectors", tags=["connectors"])

SUPPORTED_TYPES = ("google_drive", "confluence", "web_url", "notion", "web", "aws_s3", "azure_data_lake", "gcs", "sharepoint")


# ──────────────────────────────────────────────────────────────
# Request / Response schemas
# ──────────────────────────────────────────────────────────────


class ConnectorCreateRequest(BaseModel):
    name: str
    type: str
    config: dict[str, Any]
    team_id: str | None = None
    collection_id: str | None = None
    sync_interval_minutes: int = 60


class ConnectorUpdateRequest(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    sync_interval_minutes: int | None = None
    status: str | None = None  # "active" | "paused"


class ConnectorResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    last_synced_at: datetime | None
    total_docs_synced: int
    last_error: str | None
    sync_interval_minutes: int
    team_id: str | None
    collection_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectorDocumentResponse(BaseModel):
    id: str
    connector_id: str
    external_id: str
    external_url: str | None
    title: str
    document_id: str | None
    last_synced_at: datetime
    content_hash: str | None

    model_config = {"from_attributes": True}


class ConnectorDetailResponse(ConnectorResponse):
    documents: list[ConnectorDocumentResponse]


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _require_admin(user: UserContext) -> None:
    if "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )


def _connector_to_response(c: Connector) -> ConnectorResponse:
    return ConnectorResponse(
        id=c.id,
        name=c.name,
        type=c.type,
        status=c.status,
        last_synced_at=c.last_synced_at,
        total_docs_synced=c.total_docs_synced,
        last_error=c.last_error,
        sync_interval_minutes=c.sync_interval_minutes,
        team_id=c.team_id,
        collection_id=c.collection_id,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _connector_doc_to_response(cd: ConnectorDocument) -> ConnectorDocumentResponse:
    return ConnectorDocumentResponse(
        id=cd.id,
        connector_id=cd.connector_id,
        external_id=cd.external_id,
        external_url=cd.external_url,
        title=cd.title,
        document_id=cd.document_id,
        last_synced_at=cd.last_synced_at,
        content_hash=cd.content_hash,
    )


# ──────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────


@router.post("", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED)
async def create_connector(
    body: ConnectorCreateRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new external document connector (admin only).

    Immediately dispatches an initial sync task.
    """
    _require_admin(user)

    # Normalize aliases to canonical type names
    connector_type = "web_url" if body.type == "web" else body.type

    if connector_type not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported connector type '{body.type}'. Supported: {list(SUPPORTED_TYPES)}",
        )

    connector = Connector(
        id=str(uuid.uuid4()),
        name=body.name,
        type=connector_type,
        config=json.dumps(body.config),
        owner_id=user.user_id,
        team_id=body.team_id,
        collection_id=body.collection_id,
        sync_interval_minutes=body.sync_interval_minutes,
        status="active",
    )
    db.add(connector)
    await db.flush()
    await db.commit()
    await db.refresh(connector)

    # Trigger immediate initial sync
    try:
        from src.tasks.connector_tasks import sync_connector_task
        sync_connector_task.delay(connector.id)
    except Exception as dispatch_err:
        import logging
        logging.getLogger(__name__).warning(
            "Could not dispatch initial sync for connector %s: %s",
            connector.id,
            dispatch_err,
        )

    return _connector_to_response(connector)


@router.get("", response_model=list[ConnectorResponse])
async def list_connectors(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all connectors (admin only)."""
    _require_admin(user)

    result = await db.execute(select(Connector).order_by(Connector.created_at.desc()))
    connectors = result.scalars().all()
    return [_connector_to_response(c) for c in connectors]


@router.get("/{connector_id}", response_model=ConnectorDetailResponse)
async def get_connector(
    connector_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single connector with all its synced document records (admin only)."""
    _require_admin(user)

    result = await db.execute(
        select(Connector).where(Connector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found"
        )

    cd_result = await db.execute(
        select(ConnectorDocument)
        .where(ConnectorDocument.connector_id == connector_id)
        .order_by(ConnectorDocument.last_synced_at.desc())
    )
    connector_docs = cd_result.scalars().all()

    return ConnectorDetailResponse(
        id=connector.id,
        name=connector.name,
        type=connector.type,
        status=connector.status,
        last_synced_at=connector.last_synced_at,
        total_docs_synced=connector.total_docs_synced,
        last_error=connector.last_error,
        sync_interval_minutes=connector.sync_interval_minutes,
        team_id=connector.team_id,
        collection_id=connector.collection_id,
        created_at=connector.created_at,
        updated_at=connector.updated_at,
        documents=[_connector_doc_to_response(cd) for cd in connector_docs],
    )


@router.patch("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(
    connector_id: str,
    body: ConnectorUpdateRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update connector config, sync interval, or status (pause/resume). Admin only."""
    _require_admin(user)

    result = await db.execute(
        select(Connector).where(Connector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found"
        )

    if body.name is not None:
        connector.name = body.name
    if body.config is not None:
        connector.config = json.dumps(body.config)
    if body.sync_interval_minutes is not None:
        connector.sync_interval_minutes = body.sync_interval_minutes
    if body.status is not None:
        if body.status not in ("active", "paused"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="status must be 'active' or 'paused'",
            )
        connector.status = body.status

    await db.commit()
    await db.refresh(connector)
    return _connector_to_response(connector)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(
    connector_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a connector. Does NOT delete already-ingested documents. Admin only."""
    _require_admin(user)

    result = await db.execute(
        select(Connector).where(Connector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found"
        )

    await db.delete(connector)
    await db.commit()


@router.post("/{connector_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    connector_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger an immediate sync for this connector. Admin only."""
    _require_admin(user)

    result = await db.execute(
        select(Connector).where(Connector.id == connector_id)
    )
    connector = result.scalar_one_or_none()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found"
        )

    from src.tasks.connector_tasks import sync_connector_task
    sync_connector_task.delay(connector_id)

    return {"message": "Sync started"}
