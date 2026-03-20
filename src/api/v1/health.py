"""Health check endpoints — liveness, readiness, and full component status.

Endpoints
---------
GET /health          → simple liveness probe (always 200 if the process is up)
GET /health/ready    → readiness probe (503 if critical dependencies are down)
GET /health/live     → Kubernetes liveness probe (same as /health)
GET /health/full     → per-component latency breakdown (admin-level detail)
"""

from __future__ import annotations

import asyncio
import time
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_db
from src.config import get_settings, Settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


# ── Component checks ──────────────────────────────────────────────────────────

async def _check_db(db: AsyncSession) -> tuple[str, float]:
    """Return (status, latency_ms)."""
    from src.db.session import check_db_health
    t0 = time.perf_counter()
    ok = await check_db_health(db)
    ms = (time.perf_counter() - t0) * 1000
    return ("ok" if ok else "error", ms)


async def _check_ollama(settings: Settings) -> tuple[str, float]:
    """Ping the Ollama API."""
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            status = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        status = "unavailable"
    ms = (time.perf_counter() - t0) * 1000
    return (status, ms)


async def _check_redis(settings: Settings) -> tuple[str, float]:
    t0 = time.perf_counter()
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_CACHE_URL, socket_timeout=2)
        await r.ping()
        await r.aclose()
        status = "ok"
    except Exception:
        status = "unavailable"
    ms = (time.perf_counter() - t0) * 1000
    return (status, ms)


async def _check_qdrant(settings: Settings) -> tuple[str, float]:
    if settings.VECTOR_STORE_TYPE != "qdrant":
        return ("skipped", 0.0)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.QDRANT_URL}/readyz")
            status = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        status = "unavailable"
    ms = (time.perf_counter() - t0) * 1000
    return (status, ms)


async def _check_neo4j(settings: Settings) -> tuple[str, float]:
    if not settings.KNOWLEDGE_GRAPH_ENABLED:
        return ("skipped", 0.0)
    t0 = time.perf_counter()
    try:
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        async with driver.session() as session:
            await session.run("RETURN 1")
        await driver.close()
        status = "ok"
    except Exception:
        status = "unavailable"
    ms = (time.perf_counter() - t0) * 1000
    return (status, ms)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health")
@router.get("/health/live")
async def liveness(settings: Settings = Depends(get_settings)):
    """Kubernetes liveness probe — always 200 while the process is alive."""
    return {"status": "ok", "live": True, "version": settings.APP_VERSION}


@router.get("/health/ready")
async def readiness(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Kubernetes readiness probe — 503 if critical dependencies are unavailable."""
    db_status, _ = await _check_db(db)
    ollama_status, _ = await _check_ollama(settings)

    # Critical: DB must be ok; LLM degraded is acceptable for health check
    critical_ok = db_status == "ok"

    if not critical_ok:
        raise HTTPException(status_code=503, detail={
            "status": "not_ready",
            "database": db_status,
            "llm": ollama_status,
        })

    return {
        "status": "ready",
        "database": db_status,
        "llm": ollama_status,
        "version": settings.APP_VERSION,
    }


@router.get("/health/full")
async def full_health(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Full health report with per-component latency (ms).

    All checks run in parallel to keep response time low.
    """
    db_result, ollama_result, redis_result, qdrant_result, neo4j_result = await asyncio.gather(
        _check_db(db),
        _check_ollama(settings),
        _check_redis(settings),
        _check_qdrant(settings),
        _check_neo4j(settings),
    )

    components: dict[str, Any] = {
        "database":  {"status": db_result[0],     "latency_ms": round(db_result[1], 1)},
        "llm":       {"status": ollama_result[0],  "latency_ms": round(ollama_result[1], 1)},
        "redis":     {"status": redis_result[0],   "latency_ms": round(redis_result[1], 1)},
        "qdrant":    {"status": qdrant_result[0],  "latency_ms": round(qdrant_result[1], 1)},
        "neo4j":     {"status": neo4j_result[0],   "latency_ms": round(neo4j_result[1], 1)},
    }

    # Overall status
    statuses = {c["status"] for c in components.values() if c["status"] != "skipped"}
    if "error" in statuses:
        overall = "error"
    elif "unavailable" in statuses:
        overall = "degraded"
    else:
        overall = "ok"

    return {
        "status": overall,
        "version": settings.APP_VERSION,
        "components": components,
    }
