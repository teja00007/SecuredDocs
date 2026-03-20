"""Admin user-management endpoints.

All routes require admin role.

# ── Features added in this file ───────────────────────────────────────────────
# Feature 1: Organisation Branding  (GET/PATCH /admin/branding,
#             POST /admin/branding/logo, GET /admin/branding/logo)
# Feature 2: GDPR Data Export       (POST /admin/gdpr/export/{user_id},
#             DELETE /admin/gdpr/delete/{user_id})
# Feature 3: Audit Log Export       (GET /admin/audit/export,
#             GET /admin/audit/user/{user_id})
# ──────────────────────────────────────────────────────────────────────────────
"""

import csv
import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_db, get_current_user
from src.config import get_settings
from src.core.rbac import UserContext
from src.core.security import hash_password
from src.models.admin_settings import AdminSetting
from src.models.deny import ServiceAccount
from src.models.document import Document
from src.models.user import User, Role
from src.models.team import Team, TeamMembership
from src.repositories.audit_repository import AuditRepository
from src.repositories.user_repository import UserRepository
from src.repositories.team_repository import TeamRepository
from src.schemas.admin import (
    AdminUserResponse,
    AdminCreateUserRequest,
    AdminSetRolesRequest,
    AdminAddTeamRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Directory for branding file uploads
_BRANDING_DIR = Path("data/uploads/branding")


# ── Helper dependencies (defined before routes so FastAPI can resolve them) ───

def _require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    if "admin" not in user.roles and not user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def _get_user_repo(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def _get_team_repo(db: AsyncSession = Depends(get_db)) -> TeamRepository:
    return TeamRepository(db)


def _assert_same_company(admin: UserContext, target_user: User) -> None:
    """Raise 403 if admin is not super_admin and target_user belongs to a different company."""
    if admin.is_super_admin:
        return
    if target_user.company_id != admin.company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not in your company")


# ── Shared schemas ────────────────────────────────────────────────────────────

class BasicUserInfo(BaseModel):
    id: str
    username: str
    email: str

    model_config = {"from_attributes": True}


# ── User search (any authenticated user — used by team member picker) ─────────

@router.get("/users/search", response_model=list[BasicUserInfo])
async def search_users(
    q: str = "",
    limit: int = 50,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return basic user info (id/username/email) scoped to the caller's company."""
    stmt = select(User).limit(limit)
    if not current_user.is_super_admin and current_user.company_id:
        stmt = stmt.where(User.company_id == current_user.company_id)
    result = await db.execute(stmt)
    users = list(result.scalars().all())
    if q:
        q_lower = q.lower()
        users = [u for u in users if q_lower in u.username.lower() or q_lower in u.email.lower()]
    return [BasicUserInfo(id=u.id, username=u.username, email=u.email) for u in users]


def _to_response(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        roles=[r.name for r in user.roles],
        teams=[m.team_id for m in user.team_memberships],
        created_at=user.created_at,
    )


# ── List users ────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).offset(skip).limit(limit)
    if not admin.is_super_admin and admin.company_id:
        stmt = stmt.where(User.company_id == admin.company_id)
    result = await db.execute(stmt)
    users = list(result.scalars().all())
    return [_to_response(u) for u in users]


# ── Create user ───────────────────────────────────────────────────────────────

@router.post("/users", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminCreateUserRequest,
    admin: UserContext = Depends(_require_admin),
    user_repo: UserRepository = Depends(_get_user_repo),
    db: AsyncSession = Depends(get_db),
):
    if await user_repo.get_by_username(body.username):
        raise HTTPException(status_code=400, detail=f"Username '{body.username}' is already taken")
    if await user_repo.get_by_email(body.email):
        raise HTTPException(status_code=400, detail=f"Email '{body.email}' is already registered")

    user = User(
        id=str(uuid.uuid4()),
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        is_active=True,
        company_id=admin.company_id,  # inherit company from the creating admin
    )
    created = await user_repo.create(user)

    # Assign requested roles
    for role_name in body.roles:
        role = await user_repo.get_role_by_name(role_name)
        if not role:
            raise HTTPException(status_code=400, detail=f"Unknown role '{role_name}'")
        await user_repo.assign_role(created.id, role.id)

    # Refresh to get relationships
    fresh = await user_repo.get_by_id(created.id)
    await db.commit()
    return _to_response(fresh)  # type: ignore[arg-type]


# ── Get single user ───────────────────────────────────────────────────────────

@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: str,
    admin: UserContext = Depends(_require_admin),
    user_repo: UserRepository = Depends(_get_user_repo),
    db: AsyncSession = Depends(get_db),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _assert_same_company(admin, user)
    await db.commit()
    return _to_response(user)


# ── Set roles ─────────────────────────────────────────────────────────────────

@router.patch("/users/{user_id}/roles", response_model=AdminUserResponse)
async def set_user_roles(
    user_id: str,
    body: AdminSetRolesRequest,
    admin: UserContext = Depends(_require_admin),
    user_repo: UserRepository = Depends(_get_user_repo),
    db: AsyncSession = Depends(get_db),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _assert_same_company(admin, user)

    # Validate all requested roles exist
    new_roles: list[Role] = []
    for role_name in body.roles:
        role = await user_repo.get_role_by_name(role_name)
        if not role:
            raise HTTPException(status_code=400, detail=f"Unknown role '{role_name}'")
        new_roles.append(role)

    # Replace roles
    user.roles = new_roles
    await db.flush()
    fresh = await user_repo.get_by_id(user_id)
    await db.commit()
    return _to_response(fresh)  # type: ignore[arg-type]


# ── Activate / deactivate ─────────────────────────────────────────────────────

@router.patch("/users/{user_id}/activate", response_model=AdminUserResponse)
async def set_active(
    user_id: str,
    active: bool = True,
    admin: UserContext = Depends(_require_admin),
    user_repo: UserRepository = Depends(_get_user_repo),
    db: AsyncSession = Depends(get_db),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _assert_same_company(admin, user)
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    user.is_active = active
    await db.flush()
    await db.commit()
    return _to_response(user)


# ── Delete user ───────────────────────────────────────────────────────────────

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    admin: UserContext = Depends(_require_admin),
    user_repo: UserRepository = Depends(_get_user_repo),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    _assert_same_company(admin, user)
    await db.delete(user)
    await db.commit()


# ── Team membership management ────────────────────────────────────────────────

@router.post("/users/{user_id}/teams", response_model=AdminUserResponse)
async def add_user_to_team(
    user_id: str,
    body: AdminAddTeamRequest,
    _: UserContext = Depends(_require_admin),
    user_repo: UserRepository = Depends(_get_user_repo),
    team_repo: TeamRepository = Depends(_get_team_repo),
    db: AsyncSession = Depends(get_db),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    team = await team_repo.get_by_id(body.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    await team_repo.add_member(body.team_id, user_id)
    fresh = await user_repo.get_by_id(user_id)
    await db.commit()
    return _to_response(fresh)  # type: ignore[arg-type]


@router.delete("/users/{user_id}/teams/{team_id}", response_model=AdminUserResponse)
async def remove_user_from_team(
    user_id: str,
    team_id: str,
    _: UserContext = Depends(_require_admin),
    user_repo: UserRepository = Depends(_get_user_repo),
    team_repo: TeamRepository = Depends(_get_team_repo),
    db: AsyncSession = Depends(get_db),
):
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await team_repo.remove_member(team_id, user_id)
    fresh = await user_repo.get_by_id(user_id)
    await db.commit()
    return _to_response(fresh)  # type: ignore[arg-type]


# ── Analytics ─────────────────────────────────────────────────────────────────

def _get_audit_repo(db: AsyncSession = Depends(get_db)) -> AuditRepository:
    return AuditRepository(db)


@router.get("/analytics")
async def get_analytics(
    days: int = 30,
    _: UserContext = Depends(_require_admin),
    audit_repo: AuditRepository = Depends(_get_audit_repo),
    db: AsyncSession = Depends(get_db),
):
    # Run sequentially — all methods share the same AsyncSession which is not
    # safe for concurrent use via asyncio.gather.
    def _default_stats() -> dict:
        return {"total_queries": 0, "avg_latency_ms": 0, "avg_chunks_retrieved": 0, "active_users": 0, "days": days}

    async def safe(coro, default):
        try:
            return await coro
        except Exception:
            return default

    stats       = await safe(audit_repo.get_query_stats(days),                         _default_stats())
    stats_prev  = await safe(audit_repo.get_query_stats(days, offset_days=days),       _default_stats())
    per_day     = await safe(audit_repo.get_queries_per_day(days),                     [])
    top_users   = await safe(audit_repo.get_top_users(limit=10, days=days),            [])
    recent      = await safe(audit_repo.get_recent_queries(limit=20),                  [])
    unanswered  = await safe(audit_repo.get_unanswered_rate(days),                     {"total": 0, "unanswered": 0, "rate_pct": 0.0})
    feedback    = await safe(audit_repo.get_feedback_stats(days),                      {"helpful": 0, "unhelpful": 0, "satisfaction_pct": None})
    latency     = await safe(audit_repo.get_latency_percentiles(days),                 {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0})
    doc_stats   = await safe(audit_repo.get_document_stats(),                          {"total": 0, "ready": 0, "failed": 0, "processing": 0, "compliance_blocked": 0})
    zero_chunks = await safe(audit_repo.get_zero_chunk_queries(days, limit=10),        [])

    await db.commit()
    return {
        "stats": stats,
        "stats_prev": stats_prev,
        "queries_per_day": per_day,
        "top_users": top_users,
        "recent_queries": recent,
        "unanswered": unanswered,
        "feedback": feedback,
        "latency_percentiles": latency,
        "document_stats": doc_stats,
        "zero_chunk_queries": zero_chunks,
    }


# ── System Settings ───────────────────────────────────────────────────────────

# Allowlist of settings that can be changed via PATCH /admin/settings
_PATCHABLE_SETTINGS = {
    "llm_provider", "llm_model", "ollama_base_url", "invite_only", "max_upload_size_mb",
    "allowed_signup_domains",
    # RAG pipeline settings
    "hybrid_search_enabled", "query_rewriting_enabled", "query_rewrite_mode",
    "query_rewrite_count", "reranker_type", "reranker_top_n",
    "contextual_retrieval_enabled", "chunk_size", "chunk_overlap",
    "hierarchical_parent_size", "hierarchical_child_size", "retrieval_top_k",
}


async def _load_db_settings(db: AsyncSession) -> dict[str, str]:
    """Load all admin setting overrides from the database."""
    result = await db.execute(select(AdminSetting))
    return {row.key: row.value for row in result.scalars().all()}


@router.get("/settings")
async def get_system_settings(
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return current system settings (env vars merged with DB overrides)."""
    settings = get_settings()
    db_overrides = await _load_db_settings(db)
    await db.commit()

    # Merge: DB values take precedence over env vars
    llm_provider = db_overrides.get("llm_provider", settings.LLM_PROVIDER)
    llm_model = db_overrides.get("llm_model", settings.LLM_MODEL)
    ollama_base_url = db_overrides.get("ollama_base_url", settings.OLLAMA_BASE_URL)
    invite_only_raw = db_overrides.get("invite_only", None)
    invite_only = (invite_only_raw.lower() in ("true", "1", "yes")) if invite_only_raw is not None else False
    max_upload_size_mb_raw = db_overrides.get("max_upload_size_mb", None)
    max_upload_size_mb = int(max_upload_size_mb_raw) if max_upload_size_mb_raw else settings.MAX_UPLOAD_SIZE_MB

    openai_key = os.getenv("OPENAI_API_KEY") or (settings.OPENAI_API_KEY or "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY") or (settings.ANTHROPIC_API_KEY or "")

    def _bool(key: str, default: bool) -> bool:
        raw = db_overrides.get(key)
        if raw is not None:
            return raw.lower() in ("true", "1", "yes")
        return default

    def _int(key: str, default: int) -> int:
        raw = db_overrides.get(key)
        return int(raw) if raw is not None else default

    def _str(key: str, default: str) -> str:
        return db_overrides.get(key, default)

    cohere_key = os.getenv("COHERE_API_KEY", "")

    return {
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "ollama_base_url": ollama_base_url,
        "openai_api_key_set": bool(openai_key),
        "anthropic_api_key_set": bool(anthropic_key),
        "invite_only": invite_only,
        "allowed_signup_domains": db_overrides.get("allowed_signup_domains", ""),
        "max_upload_size_mb": max_upload_size_mb,
        "smtp_configured": bool(os.getenv("SMTP_HOST")),
        "redis_configured": bool(os.getenv("REDIS_URL")),
        "smtp_host": os.getenv("SMTP_HOST", ""),
        "smtp_port": os.getenv("SMTP_PORT", "587"),
        "smtp_user": os.getenv("SMTP_USER", ""),
        "smtp_from": os.getenv("SMTP_FROM", ""),
        "redis_url": os.getenv("REDIS_URL", ""),
        "openai_api_key_hint": (openai_key[:8] + "…") if openai_key else "",
        "anthropic_api_key_hint": (anthropic_key[:8] + "…") if anthropic_key else "",
        # ── RAG Pipeline Settings ──────────────────────────────────────────────
        "hybrid_search_enabled": _bool("hybrid_search_enabled", settings.HYBRID_SEARCH_ENABLED),
        "query_rewriting_enabled": _bool("query_rewriting_enabled", settings.QUERY_REWRITING_ENABLED),
        "query_rewrite_mode": _str("query_rewrite_mode", getattr(settings, "QUERY_REWRITE_MODE", "simple")),
        "query_rewrite_count": _int("query_rewrite_count", getattr(settings, "QUERY_REWRITE_COUNT", 3)),
        "reranker_type": _str("reranker_type", getattr(settings, "RERANKER_TYPE", "rrf")),
        "reranker_top_n": _int("reranker_top_n", getattr(settings, "RERANKER_TOP_N", 5)),
        "retrieval_top_k": _int("retrieval_top_k", getattr(settings, "RETRIEVAL_TOP_K", 20)),
        "contextual_retrieval_enabled": _bool("contextual_retrieval_enabled", getattr(settings, "CONTEXTUAL_RETRIEVAL_ENABLED", False)),
        "chunk_size": _int("chunk_size", settings.CHUNK_SIZE),
        "chunk_overlap": _int("chunk_overlap", settings.CHUNK_OVERLAP),
        "hierarchical_parent_size": _int("hierarchical_parent_size", getattr(settings, "HIERARCHICAL_PARENT_SIZE", 1500)),
        "hierarchical_child_size": _int("hierarchical_child_size", getattr(settings, "HIERARCHICAL_CHILD_SIZE", 200)),
        "cohere_api_key_set": bool(cohere_key),
        "cohere_api_key_hint": (cohere_key[:8] + "…") if cohere_key else "",
    }


class SettingsPatchRequest(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    ollama_base_url: str | None = None
    invite_only: bool | None = None
    allowed_signup_domains: str | None = None  # comma-separated: "tester.com,corp.io"
    max_upload_size_mb: int | None = None
    # RAG pipeline
    hybrid_search_enabled: bool | None = None
    query_rewriting_enabled: bool | None = None
    query_rewrite_mode: str | None = None
    query_rewrite_count: int | None = None
    reranker_type: str | None = None
    reranker_top_n: int | None = None
    retrieval_top_k: int | None = None
    contextual_retrieval_enabled: bool | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    hierarchical_parent_size: int | None = None
    hierarchical_child_size: int | None = None


@router.patch("/settings")
async def patch_system_settings(
    body: SettingsPatchRequest,
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update system settings (stored in DB, override env vars)."""
    updates: dict[str, str] = {}

    if body.llm_provider is not None:
        updates["llm_provider"] = body.llm_provider
    if body.llm_model is not None:
        updates["llm_model"] = body.llm_model
    if body.ollama_base_url is not None:
        updates["ollama_base_url"] = body.ollama_base_url
    if body.invite_only is not None:
        updates["invite_only"] = str(body.invite_only).lower()
    if body.allowed_signup_domains is not None:
        # Normalise: lowercase, strip whitespace, remove empty entries
        domains = [d.strip().lower().lstrip("@") for d in body.allowed_signup_domains.split(",") if d.strip()]
        updates["allowed_signup_domains"] = ",".join(domains)
    if body.max_upload_size_mb is not None:
        if body.max_upload_size_mb < 1:
            raise HTTPException(status_code=400, detail="max_upload_size_mb must be >= 1")
        updates["max_upload_size_mb"] = str(body.max_upload_size_mb)

    # RAG pipeline settings
    for bool_field in ("hybrid_search_enabled", "query_rewriting_enabled", "contextual_retrieval_enabled"):
        val = getattr(body, bool_field, None)
        if val is not None:
            updates[bool_field] = str(val).lower()

    for str_field in ("query_rewrite_mode", "reranker_type"):
        val = getattr(body, str_field, None)
        if val is not None:
            updates[str_field] = val

    for int_field in ("query_rewrite_count", "reranker_top_n", "retrieval_top_k",
                      "chunk_size", "chunk_overlap", "hierarchical_parent_size", "hierarchical_child_size"):
        val = getattr(body, int_field, None)
        if val is not None:
            if val < 1:
                raise HTTPException(status_code=400, detail=f"{int_field} must be >= 1")
            updates[int_field] = str(val)

    if not updates:
        raise HTTPException(status_code=400, detail="No valid settings provided")

    now = datetime.now(timezone.utc)
    for key, value in updates.items():
        result = await db.execute(select(AdminSetting).where(AdminSetting.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
            existing.updated_at = now
            existing.updated_by_id = admin.user_id
        else:
            db.add(AdminSetting(key=key, value=value, updated_at=now, updated_by_id=admin.user_id))

    await db.commit()
    return {"updated": list(updates.keys()), "message": "Settings updated successfully"}


# ── Env / Secrets Settings ────────────────────────────────────────────────────

def _update_env_file(updates: dict[str, str]) -> None:
    """Upsert key=value pairs in the .env file and update os.environ immediately."""
    env_path = Path(".env")
    lines: list[str] = env_path.read_text().splitlines() if env_path.exists() else []

    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            val = updates[key]
            # Preserve quoting style — use double quotes for safety
            new_lines.append(f'{key}="{val}"')
            updated_keys.add(key)
        else:
            new_lines.append(line)

    # Append any keys that were not already in the file
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f'{key}="{val}"')

    env_path.write_text("\n".join(new_lines) + "\n")


class EnvPatchRequest(BaseModel):
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    cohere_api_key: str | None = None
    smtp_host: str | None = None
    smtp_port: str | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    redis_url: str | None = None


@router.patch("/env")
async def patch_env_settings(
    body: EnvPatchRequest,
    _: UserContext = Depends(_require_admin),
):
    """Update secrets / service config — writes to os.environ and .env file."""
    env_map = {
        "OPENAI_API_KEY": body.openai_api_key,
        "ANTHROPIC_API_KEY": body.anthropic_api_key,
        "COHERE_API_KEY": body.cohere_api_key,
        "SMTP_HOST": body.smtp_host,
        "SMTP_PORT": body.smtp_port,
        "SMTP_USER": body.smtp_user,
        "SMTP_PASSWORD": body.smtp_password,
        "SMTP_FROM": body.smtp_from,
        "REDIS_URL": body.redis_url,
    }
    updates = {k: v for k, v in env_map.items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No settings provided")

    # Apply to running process immediately (no restart needed for most consumers)
    for key, value in updates.items():
        os.environ[key] = value

    # Persist to .env file
    try:
        _update_env_file(updates)
    except Exception as exc:
        # Writing .env failed (e.g. read-only FS) — env is still updated in memory
        return {
            "updated": list(updates.keys()),
            "message": "Settings applied to process. .env write failed — add manually if needed.",
            "env_write_error": str(exc),
        }

    return {"updated": list(updates.keys()), "message": "Settings saved to .env and applied"}


# ── Storage Stats ─────────────────────────────────────────────────────────────

def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


@router.get("/storage")
async def get_storage_stats(
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return storage statistics aggregated by user and team."""
    # Total counts
    total_count_result = await db.execute(select(func.count(Document.id)))
    total_documents = total_count_result.scalar() or 0

    total_size_result = await db.execute(select(func.sum(Document.file_size)))
    total_file_size = total_size_result.scalar() or 0

    # Per-user aggregation
    per_user_result = await db.execute(
        select(
            Document.owner_id,
            func.count(Document.id).label("document_count"),
            func.sum(Document.file_size).label("total_bytes"),
        )
        .group_by(Document.owner_id)
        .order_by(func.sum(Document.file_size).desc())
    )
    per_user_rows = per_user_result.all()

    # Look up usernames for those user_ids
    user_ids = [row.owner_id for row in per_user_rows]
    username_map: dict[str, str] = {}
    if user_ids:
        user_result = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        for uid, uname in user_result.all():
            username_map[uid] = uname

    by_user = [
        {
            "user_id": row.owner_id,
            "username": username_map.get(row.owner_id, row.owner_id),
            "document_count": row.document_count,
            "total_bytes": row.total_bytes or 0,
        }
        for row in per_user_rows
    ]

    # Per-team aggregation: join through DocumentTeamAccess
    from src.models.document import DocumentTeamAccess
    per_team_result = await db.execute(
        select(
            DocumentTeamAccess.team_id,
            func.count(DocumentTeamAccess.document_id).label("document_count"),
            func.sum(Document.file_size).label("total_bytes"),
        )
        .join(Document, Document.id == DocumentTeamAccess.document_id)
        .group_by(DocumentTeamAccess.team_id)
        .order_by(func.sum(Document.file_size).desc())
    )
    per_team_rows = per_team_result.all()

    team_ids = [row.team_id for row in per_team_rows]
    team_name_map: dict[str, str] = {}
    if team_ids:
        team_result = await db.execute(select(Team.id, Team.name).where(Team.id.in_(team_ids)))
        for tid, tname in team_result.all():
            team_name_map[tid] = tname

    by_team = [
        {
            "team_id": row.team_id,
            "team_name": team_name_map.get(row.team_id, row.team_id),
            "document_count": row.document_count,
            "total_bytes": row.total_bytes or 0,
        }
        for row in per_team_rows
    ]

    await db.commit()
    return {
        "total_documents": total_documents,
        "total_file_size_bytes": total_file_size,
        "total_file_size_human": _human_bytes(total_file_size),
        "by_user": by_user,
        "by_team": by_team,
    }


# ── Data Retention ────────────────────────────────────────────────────────────

class RetentionRequest(BaseModel):
    messages_older_than_days: int | None = None
    documents_older_than_days: int | None = None


@router.post("/retention")
async def apply_retention_policy(
    body: RetentionRequest,
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete old messages and/or documents according to a retention policy."""
    from datetime import timedelta
    from sqlalchemy import delete as sa_delete

    messages_deleted = 0
    documents_deleted = 0
    now = datetime.now(timezone.utc)

    # ── Messages ──────────────────────────────────────────────────────────────
    if body.messages_older_than_days is not None:
        cutoff = now - timedelta(days=body.messages_older_than_days)
        try:
            # Try soft-delete first (is_deleted column)
            from src.models.chat import Message as ChatMessage
            result = await db.execute(
                select(ChatMessage).where(ChatMessage.created_at < cutoff)
            )
            msgs = result.scalars().all()
            for msg in msgs:
                if hasattr(msg, "is_deleted"):
                    msg.is_deleted = True
                else:
                    await db.delete(msg)
                messages_deleted += 1
        except Exception:
            try:
                from src.models.conversation import ConversationMessage
                result = await db.execute(
                    select(ConversationMessage).where(ConversationMessage.created_at < cutoff)
                )
                msgs = result.scalars().all()
                for msg in msgs:
                    await db.delete(msg)
                    messages_deleted += 1
            except Exception:
                pass

    # ── Documents ─────────────────────────────────────────────────────────────
    if body.documents_older_than_days is not None:
        cutoff = now - timedelta(days=body.documents_older_than_days)
        result = await db.execute(
            select(Document).where(Document.updated_at < cutoff)
        )
        old_docs = result.scalars().all()
        for doc in old_docs:
            # Best-effort vector store cleanup
            try:
                settings = get_settings()
                from src.vectorstore import get_vector_store
                vs = get_vector_store(settings)
                vs.delete_document(doc.id)
            except Exception:
                pass
            await db.delete(doc)
            documents_deleted += 1

    await db.commit()
    return {"messages_deleted": messages_deleted, "documents_deleted": documents_deleted}


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 1: Organisation Branding
# ═══════════════════════════════════════════════════════════════════════════════

_BRANDING_KEYS = ("org_name", "logo_url", "primary_color", "favicon_url", "login_message")
_BRANDING_DEFAULTS: dict[str, str | None] = {
    "org_name": "Nexus",
    "logo_url": None,
    "primary_color": "#3F0E40",
    "favicon_url": None,
    "login_message": "Welcome to Nexus AI Knowledge Base",
}
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_URL_RE = re.compile(r"^https?://\S+$")


@router.get("/branding")
async def get_branding(db: AsyncSession = Depends(get_db)):
    """Return organisation branding config (public — no auth required)."""
    result = await db.execute(
        select(AdminSetting).where(AdminSetting.key.in_(_BRANDING_KEYS))
    )
    db_vals = {row.key: row.value for row in result.scalars().all()}
    await db.commit()

    return {
        key: db_vals.get(key, _BRANDING_DEFAULTS[key])
        for key in _BRANDING_KEYS
    }


class BrandingPatchRequest(BaseModel):
    org_name: str | None = None
    logo_url: str | None = None
    primary_color: str | None = None
    favicon_url: str | None = None
    login_message: str | None = None


@router.patch("/branding")
async def patch_branding(
    body: BrandingPatchRequest,
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update organisation branding settings (admin only)."""
    updates: dict[str, str] = {}

    if body.org_name is not None:
        updates["org_name"] = body.org_name
    if body.primary_color is not None:
        if not _HEX_COLOR_RE.match(body.primary_color):
            raise HTTPException(
                status_code=400,
                detail="primary_color must be a valid hex color in #RRGGBB format",
            )
        updates["primary_color"] = body.primary_color
    if body.logo_url is not None:
        if not _URL_RE.match(body.logo_url):
            raise HTTPException(status_code=400, detail="logo_url is not a valid URL")
        updates["logo_url"] = body.logo_url
    if body.favicon_url is not None:
        if not _URL_RE.match(body.favicon_url):
            raise HTTPException(status_code=400, detail="favicon_url is not a valid URL")
        updates["favicon_url"] = body.favicon_url
    if body.login_message is not None:
        updates["login_message"] = body.login_message

    if not updates:
        raise HTTPException(status_code=400, detail="No valid branding fields provided")

    now = datetime.now(timezone.utc)
    for key, value in updates.items():
        stmt = pg_insert(AdminSetting).values(
            key=key, value=value, updated_at=now, updated_by_id=admin.user_id
        ).on_conflict_do_update(
            index_elements=["key"],
            set_={"value": value, "updated_at": now, "updated_by_id": admin.user_id},
        )
        await db.execute(stmt)

    await db.commit()
    return {"updated": list(updates.keys()), "message": "Branding updated successfully"}


_ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg"}
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB


@router.post("/branding/logo")
async def upload_logo(
    file: UploadFile = File(...),
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upload an organisation logo (PNG, JPG, SVG, max 2 MB). Admin only."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_LOGO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type '{suffix}'. Allowed: {_ALLOWED_LOGO_EXTENSIONS}",
        )

    content = await file.read()
    if len(content) > _MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="Logo file exceeds 2 MB limit")

    _BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    logo_path = _BRANDING_DIR / f"logo{suffix}"
    logo_path.write_bytes(content)

    # Store path in admin settings
    key = "logo_path"
    now = datetime.now(timezone.utc)
    result = await db.execute(select(AdminSetting).where(AdminSetting.key == key))
    existing = result.scalar_one_or_none()
    if existing:
        existing.value = str(logo_path)
        existing.updated_at = now
        existing.updated_by_id = admin.user_id
    else:
        db.add(AdminSetting(key=key, value=str(logo_path), updated_at=now, updated_by_id=admin.user_id))

    await db.commit()
    return {"url": "/api/v1/admin/branding/logo"}


@router.get("/branding/logo")
async def get_logo(db: AsyncSession = Depends(get_db)):
    """Serve the uploaded organisation logo file (public)."""
    result = await db.execute(select(AdminSetting).where(AdminSetting.key == "logo_path"))
    setting = result.scalar_one_or_none()
    await db.commit()

    if not setting or not setting.value:
        raise HTTPException(status_code=404, detail="No logo has been uploaded")

    logo_path = Path(setting.value)
    if not logo_path.exists():
        raise HTTPException(status_code=404, detail="Logo file not found on disk")

    import mimetypes
    media_type, _ = mimetypes.guess_type(str(logo_path))
    if not media_type:
        media_type = "application/octet-stream"

    return FileResponse(path=str(logo_path), media_type=media_type)


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 2: GDPR Data Export (Subject Access Request)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/gdpr/export/{user_id}")
async def gdpr_export(
    user_id: str,
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Package all data for a user into a ZIP file and return it as a download."""
    from src.models.session import UserSession
    from src.models.conversation import Conversation, ConversationMessage
    from src.models.chat import ChatMessage
    from src.models.calendar import CalendarEvent
    from src.models.audit import QueryLog

    # ── 1. User profile ───────────────────────────────────────────────────────
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
        "is_active": user.is_active,
        "roles": [r.name for r in user.roles],
        "teams": [m.team_id for m in user.team_memberships],
    }

    # ── 2. Documents ──────────────────────────────────────────────────────────
    docs_result = await db.execute(
        select(Document).where(Document.owner_id == user_id)
    )
    docs_data = [
        {
            "id": d.id,
            "filename": d.filename,
            "created_at": d.created_at.isoformat(),
            "collection_id": d.collection_id,
        }
        for d in docs_result.scalars().all()
    ]

    # ── 3. Conversation messages ───────────────────────────────────────────────
    convs_result = await db.execute(
        select(Conversation).where(Conversation.user_id == user_id)
    )
    conversations = convs_result.scalars().all()
    conv_data: list[dict] = []
    for conv in conversations:
        msgs_result = await db.execute(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == conv.id
            ).order_by(ConversationMessage.created_at)
        )
        messages = msgs_result.scalars().all()
        for msg in messages:
            conv_data.append({
                "conversation_id": conv.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
            })

    # ── 4. Chat messages ──────────────────────────────────────────────────────
    chat_result = await db.execute(
        select(ChatMessage).where(ChatMessage.sender_id == user_id)
        .order_by(ChatMessage.created_at)
    )
    chat_data = [
        {
            "channel_id": m.channel_id,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in chat_result.scalars().all()
    ]

    # ── 5. Calendar events ────────────────────────────────────────────────────
    cal_result = await db.execute(
        select(CalendarEvent).where(CalendarEvent.created_by == user_id)
    )
    cal_data = [
        {
            "title": e.title,
            "start_time": e.start_time.isoformat(),
            "end_time": e.end_time.isoformat(),
        }
        for e in cal_result.scalars().all()
    ]

    # ── 6. Audit log entries ──────────────────────────────────────────────────
    audit_result = await db.execute(
        select(QueryLog).where(QueryLog.user_id == user_id)
        .order_by(QueryLog.created_at.desc())
    )
    audit_data = [
        {
            "query_text": log.query_text,
            "created_at": log.created_at.isoformat(),
            "latency_ms": log.latency_ms,
        }
        for log in audit_result.scalars().all()
    ]

    # ── 7. Active sessions ────────────────────────────────────────────────────
    sessions_result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.is_revoked == False,  # noqa: E712
        )
    )
    sessions_data = [
        {
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at.isoformat(),
        }
        for s in sessions_result.scalars().all()
    ]

    await db.commit()

    # ── Build ZIP in memory ───────────────────────────────────────────────────
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.json", json.dumps(profile, indent=2, default=str))
        zf.writestr("documents.json", json.dumps(docs_data, indent=2, default=str))
        zf.writestr("conversations.json", json.dumps(conv_data, indent=2, default=str))
        zf.writestr("chat_messages.json", json.dumps(chat_data, indent=2, default=str))
        zf.writestr("calendar_events.json", json.dumps(cal_data, indent=2, default=str))
        zf.writestr("audit_log.json", json.dumps(audit_data, indent=2, default=str))
        zf.writestr("sessions.json", json.dumps(sessions_data, indent=2, default=str))

    buf.seek(0)
    today = datetime.now(timezone.utc).date().isoformat()
    filename = f"gdpr_export_{user_id}_{today}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/gdpr/delete/{user_id}")
async def gdpr_delete(
    user_id: str,
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Right-to-be-forgotten: delete or anonymize all data for a user."""
    from sqlalchemy import update as sa_update
    from src.models.conversation import Conversation
    from src.models.chat import ChatMessage
    from src.models.audit import QueryLog

    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account via GDPR endpoint")

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    records_affected = 0

    # 1. Anonymize documents: prefix filename, set owner_id to NULL via raw UPDATE.
    #    We use execute(sa_update(...)) to bypass the Python-level Mapped[str] type check.
    docs_to_anon = (await db.execute(
        select(Document.id, Document.filename).where(Document.owner_id == user_id)
    )).all()
    for doc_id, doc_filename in docs_to_anon:
        new_name = doc_filename if doc_filename.startswith("deleted_user_") else f"deleted_user_{doc_filename}"
        await db.execute(
            sa_update(Document)
            .where(Document.id == doc_id)
            .values(filename=new_name, owner_id=None)
        )
        records_affected += 1

    # 2. Anonymize conversations (user_id → NULL via raw UPDATE)
    conv_rows = (await db.execute(
        select(Conversation.id).where(Conversation.user_id == user_id)
    )).all()
    if conv_rows:
        conv_ids = [r[0] for r in conv_rows]
        await db.execute(
            sa_update(Conversation)
            .where(Conversation.id.in_(conv_ids))
            .values(user_id=None)
        )
        records_affected += len(conv_ids)

    # 3. Anonymize chat messages (set content to "[deleted]", sender_id to "")
    chat_rows = (await db.execute(
        select(ChatMessage.id).where(ChatMessage.sender_id == user_id)
    )).all()
    if chat_rows:
        chat_ids = [r[0] for r in chat_rows]
        await db.execute(
            sa_update(ChatMessage)
            .where(ChatMessage.id.in_(chat_ids))
            .values(content="[deleted]", sender_id="", sender_username="[deleted]")
        )
        records_affected += len(chat_ids)

    # 4. Anonymize audit logs (clear query_text, user_id → NULL via raw UPDATE)
    audit_rows = (await db.execute(
        select(QueryLog.id).where(QueryLog.user_id == user_id)
    )).all()
    if audit_rows:
        audit_ids = [r[0] for r in audit_rows]
        await db.execute(
            sa_update(QueryLog)
            .where(QueryLog.id.in_(audit_ids))
            .values(query_text="", user_id=None)
        )
        records_affected += len(audit_ids)

    await db.flush()

    # 5. Delete the user record (cascades sessions, team memberships, roles)
    await db.delete(user)
    records_affected += 1

    await db.commit()
    return {"status": "deleted", "records_affected": records_affected}


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 3: Audit Log Export
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/audit/export")
async def export_audit_log(
    start_date: str = Query(..., description="Start date inclusive, ISO format YYYY-MM-DD"),
    end_date: str = Query(..., description="End date inclusive, ISO format YYYY-MM-DD"),
    user_id: str | None = Query(default=None),
    format: str = Query(default="csv", description="'csv' or 'json'"),
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Export audit log entries for a date range as CSV or JSON file download."""
    from datetime import timedelta
    from src.models.audit import QueryLog

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        # end_date is inclusive — add one day so we capture the whole day
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date and end_date must be YYYY-MM-DD")

    if format not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'json'")

    stmt = select(QueryLog).where(
        QueryLog.created_at >= start_dt,
        QueryLog.created_at < end_dt,
    ).order_by(QueryLog.created_at)

    if user_id:
        stmt = stmt.where(QueryLog.user_id == user_id)

    result = await db.execute(stmt)
    logs = result.scalars().all()

    # Build username map
    log_user_ids = list({log.user_id for log in logs if log.user_id})
    username_map: dict[str, str] = {}
    if log_user_ids:
        ur = await db.execute(select(User.id, User.username).where(User.id.in_(log_user_ids)))
        username_map = {uid: uname for uid, uname in ur.all()}

    await db.commit()

    rows = [
        {
            "id": log.id,
            "user_id": log.user_id or "",
            "username": username_map.get(log.user_id or "", ""),
            "action": "query",
            "query_text": (log.query_text or "")[:200],
            "document_id": "",
            "created_at": log.created_at.isoformat(),
            "latency_ms": log.latency_ms,
            "status": "success",
        }
        for log in logs
    ]

    filename_base = f"audit_export_{start_date}_{end_date}"

    if format == "json":
        content = json.dumps(rows, indent=2, default=str).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename_base}.json"'},
        )

    # CSV format
    output = io.StringIO()
    fieldnames = ["id", "user_id", "username", "action", "query_text", "document_id", "created_at", "latency_ms", "status"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = output.getvalue().encode("utf-8")

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename_base}.csv"'},
    )


@router.get("/audit/user/{user_id}")
async def get_user_audit_trail(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return full audit trail for a specific user (paginated)."""
    from src.models.audit import QueryLog, IngestionLog, DocumentAuditLog, TeamAuditLog

    entries: list[dict] = []

    # Query logs
    q_result = await db.execute(
        select(QueryLog)
        .where(QueryLog.user_id == user_id)
        .order_by(QueryLog.created_at.desc())
    )
    for log in q_result.scalars().all():
        entries.append({
            "id": log.id,
            "action": "query",
            "detail": (log.query_text or "")[:200],
            "created_at": log.created_at.isoformat(),
            "ip_address": None,
        })

    # Ingestion logs
    i_result = await db.execute(
        select(IngestionLog)
        .where(IngestionLog.user_id == user_id)
        .order_by(IngestionLog.created_at.desc())
    )
    for log in i_result.scalars().all():
        entries.append({
            "id": log.id,
            "action": "document_upload",
            "detail": f"document_id={log.document_id} status={log.status}",
            "created_at": log.created_at.isoformat(),
            "ip_address": None,
        })

    # Document audit logs
    da_result = await db.execute(
        select(DocumentAuditLog)
        .where(DocumentAuditLog.user_id == user_id)
        .order_by(DocumentAuditLog.created_at.desc())
    )
    for log in da_result.scalars().all():
        entries.append({
            "id": log.id,
            "action": f"document_{log.action}",
            "detail": f"document_id={log.document_id}",
            "created_at": log.created_at.isoformat(),
            "ip_address": None,
        })

    # Team audit logs
    ta_result = await db.execute(
        select(TeamAuditLog)
        .where(TeamAuditLog.user_id == user_id)
        .order_by(TeamAuditLog.created_at.desc())
    )
    for log in ta_result.scalars().all():
        entries.append({
            "id": log.id,
            "action": f"team_{log.action}",
            "detail": f"team_id={log.team_id}",
            "created_at": log.created_at.isoformat(),
            "ip_address": None,
        })

    await db.commit()

    # Sort all entries by created_at descending and paginate
    entries.sort(key=lambda x: x["created_at"], reverse=True)
    return entries[offset: offset + limit]


# ═══════════════════════════════════════════════════════════════════════════════
# FEATURE 4: User Activity Report
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/reports/activity")
async def get_user_activity_report(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return per-user activity: doc count, last login, join date."""
    # Count total users for pagination metadata
    total_result = await db.execute(select(func.count()).select_from(User))
    total = total_result.scalar_one()

    # Build a subquery for doc_count per user
    doc_count_subq = (
        select(Document.owner_id, func.count(Document.id).label("doc_count"))
        .group_by(Document.owner_id)
        .subquery()
    )

    # Build a subquery for team_count per user
    team_count_subq = (
        select(TeamMembership.user_id, func.count(TeamMembership.team_id).label("team_count"))
        .group_by(TeamMembership.user_id)
        .subquery()
    )

    # Main query: users left-joined to doc and team subqueries
    stmt = (
        select(
            User,
            func.coalesce(doc_count_subq.c.doc_count, 0).label("doc_count"),
            func.coalesce(team_count_subq.c.team_count, 0).label("team_count"),
        )
        .outerjoin(doc_count_subq, User.id == doc_count_subq.c.owner_id)
        .outerjoin(team_count_subq, User.id == team_count_subq.c.user_id)
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(stmt)
    rows = result.all()

    await db.commit()

    items = []
    for user_obj, doc_count, team_count in rows:
        items.append({
            "id": user_obj.id,
            "username": user_obj.username,
            "email": user_obj.email,
            "is_active": user_obj.is_active,
            "roles": [r.name for r in user_obj.roles],
            "created_at": user_obj.created_at.isoformat(),
            "last_login": None,  # User model has no last_login field
            "doc_count": doc_count,
            "team_count": team_count,
        })

    return {"total": total, "items": items}


# ── Service Accounts ──────────────────────────────────────────────────────────

import secrets


class ServiceAccountCreateRequest(BaseModel):
    name: str
    roles: list[str] = ["viewer"]
    expires_at: str | None = None  # ISO date string e.g. "2027-01-01"


@router.get("/service-accounts")
async def list_service_accounts(
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all service accounts for this company."""
    result = await db.execute(
        select(ServiceAccount)
        .where(ServiceAccount.company_id == admin.company_id)
        .order_by(ServiceAccount.created_at.desc())
    )
    accounts = result.scalars().all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "roles": a.get_roles(),
            "is_active": a.is_active,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
            "created_at": a.created_at.isoformat(),
        }
        for a in accounts
    ]


@router.post("/service-accounts", status_code=201)
async def create_service_account(
    body: ServiceAccountCreateRequest,
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new service account. Returns the plain API key once — store it safely."""
    plain_key = "sa_" + secrets.token_urlsafe(40)
    expires = None
    if body.expires_at:
        try:
            expires = datetime.fromisoformat(body.expires_at).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="expires_at must be an ISO date string")

    account = ServiceAccount(
        id=str(uuid.uuid4()),
        name=body.name,
        company_id=admin.company_id,
        roles=",".join(body.roles),
        hashed_api_key=hashlib.sha256(plain_key.encode()).hexdigest(),
        is_active=True,
        created_by=admin.user_id,
        expires_at=expires,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return {
        "id": account.id,
        "name": account.name,
        "roles": account.get_roles(),
        "is_active": account.is_active,
        "expires_at": account.expires_at.isoformat() if account.expires_at else None,
        "created_at": account.created_at.isoformat(),
        "plain_api_key": plain_key,
    }


@router.delete("/service-accounts/{account_id}", status_code=204)
async def revoke_service_account(
    account_id: str,
    admin: UserContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revoke (deactivate) a service account."""
    result = await db.execute(
        select(ServiceAccount).where(
            ServiceAccount.id == account_id,
            ServiceAccount.company_id == admin.company_id,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Service account not found")
    account.is_active = False
    await db.commit()
