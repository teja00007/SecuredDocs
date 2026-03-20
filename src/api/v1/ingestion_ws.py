"""WebSocket endpoint for real-time ingestion job progress.

Clients connect to:
    ws://<host>/api/v1/ingestion/ws/{job_id}

The server polls the IngestionJob row every second and pushes JSON updates:
    {"job_id": "...", "status": "processing", "progress_pct": 42.0, ...}

The connection closes automatically when the job reaches a terminal state
(completed | failed) or after TIMEOUT_SECONDS without any DB row found.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from src.db.session import get_async_engine, get_session_factory, get_async_session
from src.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ingestion"])

_POLL_INTERVAL = 1.0      # seconds between DB polls
_TIMEOUT = 600            # max seconds before force-close (10 min)
_TERMINAL = {"completed", "failed"}


@router.websocket("/ingestion/ws/{job_id}")
async def ingestion_progress_ws(websocket: WebSocket, job_id: str) -> None:
    """Stream ingestion job progress to the client."""
    await websocket.accept()
    settings = get_settings()
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    elapsed = 0.0
    try:
        while elapsed < _TIMEOUT:
            job_data = await _fetch_job(factory, job_id)

            if job_data is None:
                await websocket.send_text(json.dumps({
                    "job_id": job_id,
                    "status": "not_found",
                    "error": "Job not found",
                }))
                break

            await websocket.send_text(json.dumps(job_data))

            if job_data.get("status") in _TERMINAL:
                break

            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

        if elapsed >= _TIMEOUT:
            await websocket.send_text(json.dumps({
                "job_id": job_id,
                "status": "timeout",
                "error": "WebSocket timed out waiting for job completion",
            }))

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected for job %s", job_id)
    except Exception as exc:
        logger.error("WebSocket error for job %s: %s", job_id, exc)
        try:
            await websocket.send_text(json.dumps({"error": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        await engine.dispose()


async def _fetch_job(factory, job_id: str) -> dict | None:
    """Return the job as a dict, or None if not found."""
    from src.models.ingestion_job import IngestionJob
    async for db in get_async_session(factory):
        result = await db.execute(
            select(IngestionJob).where(IngestionJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return None
        return job.to_dict()
    return None
