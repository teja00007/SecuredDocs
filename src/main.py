"""FastAPI application entry point."""

# ── Structured logging must be configured before anything else logs ───────────
from src.core.logging_config import setup_logging
setup_logging()
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# SlowAPI rate limiting
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from src.core.rate_limit import limiter

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, Gauge

from src.api.v1 import v1_router
from src.config import get_settings
from src.core.exceptions import (
    AuthenticationError, AuthorizationError, DocumentNotFoundError,
    CollectionNotFoundError, TeamNotFoundError, UnsupportedFileTypeError,
    VectorStoreError, LLMError,
)
from src.db.session import get_async_engine, get_session_factory


import logging as _logging
_logger = _logging.getLogger(__name__)
logger = _logging.getLogger(__name__)

# ── Custom Prometheus metrics for RAG-specific tracking ───────────────────────
rag_queries_total = Counter(
    "nexus_rag_queries_total",
    "Total RAG queries",
    ["status"],
)
rag_query_duration = Histogram(
    "nexus_rag_query_duration_seconds",
    "RAG query duration",
)
documents_total = Gauge(
    "nexus_documents_total",
    "Total documents ingested",
)
active_ws_connections = Gauge(
    "nexus_websocket_connections_active",
    "Active WebSocket connections",
)
# ─────────────────────────────────────────────────────────────────────────────

# ── Simple in-memory sliding-window rate limiter ──────────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
_rate_lock = asyncio.Lock()

_RATE_WINDOW   = 60    # seconds
_RATE_MAX_REQ  = 2000  # max requests per window per IP (high for dev; lower in prod)

# Paths exempt from rate limiting (health checks, static assets)
_RATE_EXEMPT_PREFIXES = ("/api/v1/health",)


async def check_event_reminders() -> None:
    """Run every 5 minutes, send in-app notifications for upcoming events."""
    settings = get_settings()
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            from sqlalchemy import select, and_
            from src.models.calendar import CalendarEvent
            from src.models.notification import Notification
            from src.db.session import get_async_engine, get_session_factory, get_async_session

            engine = get_async_engine(settings.DATABASE_URL)
            factory = get_session_factory(engine)

            async for db in get_async_session(factory):
                now = datetime.now(timezone.utc)
                # Find events with a reminder_minutes set and reminder not yet sent
                # where start_time is within [now + reminder_minutes - 2min, now + reminder_minutes + 2min]
                result = await db.execute(
                    select(CalendarEvent).where(
                        and_(
                            CalendarEvent.reminder_minutes.is_not(None),
                            CalendarEvent.reminder_sent == False,  # noqa: E712
                            CalendarEvent.is_cancelled == False,   # noqa: E712
                        )
                    )
                )
                events = list(result.scalars().all())

                for ev in events:
                    if ev.reminder_minutes is None:
                        continue
                    reminder_at = ev.start_time - timedelta(minutes=ev.reminder_minutes)
                    # Check if the reminder window has arrived (within ±2 minutes of now)
                    if abs((reminder_at - now).total_seconds()) <= 120:
                        # Collect all attendees + creator for notification
                        user_ids_to_notify: set[str] = {ev.created_by}
                        for attendee in ev.attendees:
                            if attendee.status != "declined":
                                user_ids_to_notify.add(attendee.user_id)

                        for uid in user_ids_to_notify:
                            notif = Notification(
                                id=str(uuid.uuid4()),
                                user_id=uid,
                                type="event_reminder",
                                title=f"Reminder: {ev.title}",
                                body=(
                                    f"Your event '{ev.title}' starts in "
                                    f"{ev.reminder_minutes} minute(s) at "
                                    f"{ev.start_time.strftime('%H:%M UTC')}."
                                ),
                                link=f"/calendar?event={ev.id}",
                            )
                            db.add(notif)

                        ev.reminder_sent = True

                await db.commit()
            await engine.dispose()

        except Exception as e:
            _logger.warning("Reminder check failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = None

    try:
        # Ensure data directories exist
        Path("data/uploads").mkdir(parents=True, exist_ok=True)
        Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)

        # Create DB tables (development convenience — use Alembic in production)
        from src.db.base import Base
        import src.models.user  # noqa: F401 — register models
        import src.models.team  # noqa: F401
        import src.models.document  # noqa: F401
        import src.models.audit  # noqa: F401
        import src.models.compliance  # noqa: F401
        import src.models.conversation  # noqa: F401
        import src.models.chat  # noqa: F401
        import src.models.calendar  # noqa: F401
        import src.models.notification  # noqa: F401
        import src.models.admin_settings  # noqa: F401
        import src.models.invite  # noqa: F401 — Phase-1: invite-only registration
        import src.models.session  # noqa: F401 — Phase-1: session management
        # Slack features: register MessageReaction so its table is created
        from src.models.chat import MessageReaction  # noqa: F401
        # Phase-2 models
        import src.models.connector  # noqa: F401
        import src.models.api_key  # noqa: F401
        import src.models.webhook  # noqa: F401
        import src.models.embed  # noqa: F401 — Phase-3: embeddable widget tokens
        import src.models.deny  # noqa: F401 — deny lists + service accounts
        import src.models.ingestion_job  # noqa: F401 — ingestion progress tracking
        import src.models.training  # noqa: F401 — training dataset curation

        engine = get_async_engine(settings.DATABASE_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Apply column migrations for existing tables (safe to run repeatedly)
            await conn.run_sync(_add_missing_columns)
        await engine.dispose()

        # Seed default roles if not present
        await _seed_roles(settings)

        # Load BM25 index from disk (singleton — safe to call multiple times)
        try:
            from src.services.bm25_service import BM25Service
            _bm25 = BM25Service()
            _logger.info("BM25 index ready: %d chunks loaded.", len(_bm25._chunk_store))
        except Exception as bm25_exc:
            _logger.warning("BM25 index load failed (non-fatal): %s", bm25_exc)

        # Ensure Neo4j indexes exist (non-fatal — KG is optional)
        try:
            from src.services.knowledge_graph_service import get_kg_service
            _kg = get_kg_service(settings)
            if _kg:
                await _kg.ensure_indexes()
                _logger.info("Neo4j KnowledgeGraph indexes ready.")
        except Exception as kg_exc:
            _logger.warning("Neo4j startup failed (non-fatal): %s", kg_exc)

        # OpenTelemetry setup (non-fatal)
        try:
            from src.telemetry import setup_telemetry
            setup_telemetry(
                service_name=settings.OTEL_SERVICE_NAME,
                otlp_endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                enabled=settings.OTEL_ENABLED,
            )
        except Exception as otel_exc:
            _logger.warning("OpenTelemetry setup failed (non-fatal): %s", otel_exc)

        # Start background reminder checker
        reminder_task = asyncio.create_task(check_event_reminders())

    except Exception as exc:
        _logger.critical("Startup failed: %s", exc, exc_info=True)
        raise

    yield

    # Cleanup on shutdown
    reminder_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass
    if engine:
        await engine.dispose()


def _add_missing_columns(conn) -> None:
    """Add columns that exist in the ORM models but are missing from the DB.

    SQLAlchemy's create_all only creates missing *tables*, not missing *columns*.
    This runs synchronously inside engine.begin() via run_sync.
    Supports both SQLite (PRAGMA) and PostgreSQL (information_schema).
    """
    from sqlalchemy import text

    # Detect database dialect
    dialect = conn.dialect.name  # "sqlite" or "postgresql"

    def _column_exists(table: str, column: str) -> bool:
        try:
            if dialect == "sqlite":
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                return column in {row[1] for row in rows}
            else:  # postgresql
                result = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ), {"t": table, "c": column}).fetchone()
                return result is not None
        except Exception:
            return True  # Assume exists on error — safer than crashing

    def _table_exists(table: str) -> bool:
        try:
            if dialect == "sqlite":
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                return len(rows) > 0
            else:
                result = conn.execute(text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = :t"
                ), {"t": table}).fetchone()
                return result is not None
        except Exception:
            return False

    # Normalize column type for the target dialect
    def _col_def(sqlite_def: str) -> str:
        if dialect == "sqlite":
            return sqlite_def
        # PostgreSQL type mapping
        d = sqlite_def
        d = d.replace("DATETIME DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP DEFAULT NOW()")
        d = d.replace("DATETIME", "TIMESTAMP")
        d = d.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
        d = d.replace("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE")
        return d

    # Map: (table, column, sqlite_column_def)
    migrations = [
        # Phase-3 additions
        ("conversation_messages", "feedback", "INTEGER"),
        # Chat tables (created fresh, but guard in case of partial old DBs)
        ("channels", "team_id", "VARCHAR(36)"),
        # Profile fields
        ("users", "display_name", "VARCHAR(255)"),
        ("users", "bio", "VARCHAR(500)"),
        ("documents", "review_cycle_days", "INTEGER"),
        # Phase-1: password reset
        ("users", "password_reset_token", "VARCHAR(64)"),
        ("users", "password_reset_expires", "DATETIME"),
        # Phase-1: TOTP two-factor authentication
        ("users", "totp_secret", "VARCHAR(64)"),
        ("users", "totp_enabled", "BOOLEAN DEFAULT 0"),
        ("users", "totp_backup_codes", "VARCHAR(1024)"),
        # Calendar recurring events + reminders
        ("calendar_events", "location", "VARCHAR(500)"),
        ("calendar_events", "recurrence_rule", "VARCHAR(500)"),
        ("calendar_events", "recurrence_parent_id", "VARCHAR(36)"),
        ("calendar_events", "is_cancelled", "BOOLEAN DEFAULT 0"),
        ("calendar_events", "reminder_minutes", "INTEGER"),
        ("calendar_events", "reminder_sent", "BOOLEAN DEFAULT 0"),
        # Document versioning + folder support
        ("documents", "current_version", "INTEGER DEFAULT 1"),
        ("documents", "folder_id", "VARCHAR(36)"),
        ("documents", "updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
        # Slack features — Feature 1: threading
        ("chat_messages", "parent_id", "VARCHAR(36)"),
        ("chat_messages", "thread_count", "INTEGER DEFAULT 0"),
        ("chat_messages", "last_reply_at", "DATETIME"),
        # Slack features — Feature 2: edit / soft delete
        ("chat_messages", "edited_at", "DATETIME"),
        ("chat_messages", "deleted_at", "DATETIME"),
        ("chat_messages", "is_deleted", "BOOLEAN DEFAULT 0"),
        # Slack features — Feature 7: pinning
        ("chat_messages", "is_pinned", "BOOLEAN DEFAULT 0"),
        ("chat_messages", "pinned_by_id", "VARCHAR(36)"),
        ("chat_messages", "pinned_at", "DATETIME"),
        # Phase-2: OAuth SSO columns
        ("users", "oauth_provider", "VARCHAR(32)"),
        ("users", "oauth_provider_id", "VARCHAR(256)"),
        # Phase-2: Post-huddle pipeline columns
        ("calendar_events", "meeting_notes", "TEXT"),
        ("calendar_events", "transcript_document_id", "VARCHAR(36)"),
        ("calendar_events", "summary_document_id", "VARCHAR(36)"),
        ("calendar_events", "agenda", "TEXT"),
        # RBAC / multi-tenant columns
        ("users", "email_verified", "BOOLEAN DEFAULT 0"),
        ("users", "email_verification_token", "VARCHAR(64)"),
        ("users", "company_id", "VARCHAR(36)"),
        ("users", "is_super_admin", "BOOLEAN DEFAULT 0"),
    ]

    for table, column, col_def_sqlite in migrations:
        try:
            if not _table_exists(table):
                continue  # create_all will create the full table
            if not _column_exists(table, column):
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {_col_def(col_def_sqlite)}"
                ))
        except Exception:
            pass  # Ignore — column may already exist or table not yet created


async def _seed_roles(settings) -> None:
    """Insert default roles (admin, analyst, viewer) if not present."""
    from src.db.session import get_async_engine, get_session_factory, get_async_session
    from src.models.user import Role
    from sqlalchemy import select

    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    default_roles = [
        Role(name="admin", description="Full system access"),
        Role(name="analyst", description="Read/write documents and run queries"),
        Role(name="viewer", description="Read documents and run queries"),
    ]

    async for session in get_async_session(factory):
        for role in default_roles:
            result = await session.execute(select(Role).where(Role.name == role.name))
            if not result.scalar_one_or_none():
                session.add(role)
        await session.commit()

    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Enterprise RAG System",
        version=settings.APP_VERSION,
        description="RBAC-aware retrieval-augmented generation with multi-format document ingestion",
        lifespan=lifespan,
    )

    # ── SlowAPI rate limiter (decorator-based, per-endpoint limits) ────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    # ──────────────────────────────────────────────────────────────────────────

    # GZip response compression (for responses > 1KB)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Request ID — adds X-Request-ID header to every response for tracing
    class RequestIDMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

    app.add_middleware(RequestIDMiddleware)

    # Rate limiting — sliding window per client IP (120 req / 60s)
    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Skip exempt paths
            if any(request.url.path.startswith(p) for p in _RATE_EXEMPT_PREFIXES):
                return await call_next(request)
            ip = (request.client.host if request.client else "unknown")
            now = time.time()
            async with _rate_lock:
                _rate_store[ip] = [t for t in _rate_store[ip] if now - t < _RATE_WINDOW]
                if len(_rate_store[ip]) >= _RATE_MAX_REQ:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many requests — slow down and try again.", "error_code": "RATE_LIMITED"},
                        headers={"Retry-After": str(_RATE_WINDOW)},
                    )
                _rate_store[ip].append(now)
            return await call_next(request)

    app.add_middleware(RateLimitMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Embed CORS middleware (runs before global CORSMiddleware) ──────────────
    # Embed endpoints are public and must accept requests from any origin
    # (file://, external sites). Global CORS can't use * with credentials,
    # so we handle embed routes separately here.
    _EMBED_CORS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Authorization, Content-Type",
    }

    @app.middleware("http")
    async def embed_cors_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/v1/embed/"):
            if request.method == "OPTIONS":
                from starlette.responses import Response as StarletteResponse
                return StarletteResponse(status_code=204, headers=_EMBED_CORS)
            try:
                response = await call_next(request)
            except Exception:
                from starlette.responses import JSONResponse as StarletteJSONResponse
                return StarletteJSONResponse(
                    {"detail": "Internal server error"},
                    status_code=500,
                    headers=_EMBED_CORS,
                )
            for k, v in _EMBED_CORS.items():
                response.headers[k] = v
            return response
        return await call_next(request)

    # ── Request / Response structured logging middleware ───────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - start) * 1000
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": request.client.host if request.client else None,
            }
        )
        return response
    # ──────────────────────────────────────────────────────────────────────────

    # ──────────────────────────────────────────────
    # Exception handlers
    # ──────────────────────────────────────────────

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(request: Request, exc: AuthenticationError):
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc), "error_code": "INVALID_CREDENTIALS"},
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(request: Request, exc: AuthorizationError):
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc), "error_code": "INSUFFICIENT_PERMISSIONS"},
        )

    @app.exception_handler(DocumentNotFoundError)
    async def document_not_found_handler(request: Request, exc: DocumentNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": "DOCUMENT_NOT_FOUND"},
        )

    @app.exception_handler(CollectionNotFoundError)
    async def collection_not_found_handler(request: Request, exc: CollectionNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": "COLLECTION_NOT_FOUND"},
        )

    @app.exception_handler(TeamNotFoundError)
    async def team_not_found_handler(request: Request, exc: TeamNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": "TEAM_NOT_FOUND"},
        )

    @app.exception_handler(UnsupportedFileTypeError)
    async def unsupported_file_type_handler(request: Request, exc: UnsupportedFileTypeError):
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "error_code": "UNSUPPORTED_FILE_TYPE"},
        )

    @app.exception_handler(VectorStoreError)
    async def vector_store_error_handler(request: Request, exc: VectorStoreError):
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "error_code": "VECTOR_STORE_ERROR"},
        )

    @app.exception_handler(LLMError)
    async def llm_error_handler(request: Request, exc: LLMError):
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "error_code": "LLM_ERROR"},
        )

    # ──────────────────────────────────────────────
    # Routers
    # ──────────────────────────────────────────────
    app.include_router(v1_router)

    # ── Prometheus instrumentation (Feature 5) ────────────────────────────────
    # Controlled by ENABLE_METRICS env var — set to "true" in docker-compose.
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/health", "/metrics"],
        env_var_name="ENABLE_METRICS",
        inprogress_name="nexus_inprogress_requests",
        inprogress_labels=True,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    # ──────────────────────────────────────────────────────────────────────────

    return app


app = create_app()
