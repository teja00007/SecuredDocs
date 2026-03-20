"""Create all database tables from SQLAlchemy models.

Used as the Docker startup step instead of alembic when no migrations exist.
"""

import asyncio
import os
import sys

sys.path.insert(0, "/app")

from src.db.base import Base
from src.db.session import get_async_engine

# Import all models so Base.metadata is populated
import src.models.user          # noqa: F401
import src.models.team          # noqa: F401
import src.models.document      # noqa: F401
import src.models.audit         # noqa: F401
import src.models.compliance    # noqa: F401
import src.models.conversation  # noqa: F401
import src.models.calendar      # noqa: F401
import src.models.notification  # noqa: F401
import src.models.chat          # noqa: F401
import src.models.admin_settings  # noqa: F401
import src.models.invite          # noqa: F401
import src.models.session         # noqa: F401
import src.models.connector       # noqa: F401
import src.models.api_key         # noqa: F401
import src.models.webhook         # noqa: F401
import src.models.company         # noqa: F401


def _add_missing_columns(conn) -> None:
    """Add columns present in ORM models but missing from existing tables.

    SQLAlchemy's create_all only creates missing tables, not missing columns.
    Supports both SQLite (PRAGMA) and PostgreSQL (information_schema).
    """
    from sqlalchemy import text

    dialect = conn.dialect.name  # "sqlite" or "postgresql"

    def _column_exists(table: str, column: str) -> bool:
        try:
            if dialect == "sqlite":
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                return column in {row[1] for row in rows}
            else:
                result = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c"
                ), {"t": table, "c": column}).fetchone()
                return result is not None
        except Exception:
            return True  # assume exists on error

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

    def _col_def(sqlite_def: str) -> str:
        if dialect == "sqlite":
            return sqlite_def
        d = sqlite_def
        d = d.replace("DATETIME DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP DEFAULT NOW()")
        d = d.replace("DATETIME", "TIMESTAMP")
        d = d.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
        d = d.replace("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE")
        return d

    migrations = [
        ("users", "display_name", "VARCHAR(255)"),
        ("users", "bio", "VARCHAR(500)"),
        ("users", "password_reset_token", "VARCHAR(64)"),
        ("users", "password_reset_expires", "DATETIME"),
        ("users", "totp_secret", "VARCHAR(64)"),
        ("users", "totp_enabled", "BOOLEAN DEFAULT 0"),
        ("users", "totp_backup_codes", "VARCHAR(1024)"),
        ("users", "oauth_provider", "VARCHAR(32)"),
        ("users", "oauth_provider_id", "VARCHAR(256)"),
        ("users", "email_verified", "BOOLEAN DEFAULT 0"),
        ("users", "email_verification_token", "VARCHAR(64)"),
        ("users", "company_id", "VARCHAR(36)"),
        ("users", "is_super_admin", "BOOLEAN DEFAULT 0"),
        # Teams multi-tenant
        ("teams", "company_id", "VARCHAR(36)"),
        ("teams", "updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
        # Collections multi-tenant
        ("collections", "company_id", "VARCHAR(36)"),
        ("conversation_messages", "feedback", "INTEGER"),
        ("channels", "team_id", "VARCHAR(36)"),
        ("documents", "review_cycle_days", "INTEGER"),
        ("documents", "current_version", "INTEGER DEFAULT 1"),
        ("documents", "folder_id", "VARCHAR(36)"),
        ("documents", "updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
        ("calendar_events", "location", "VARCHAR(500)"),
        ("calendar_events", "recurrence_rule", "VARCHAR(500)"),
        ("calendar_events", "recurrence_parent_id", "VARCHAR(36)"),
        ("calendar_events", "is_cancelled", "BOOLEAN DEFAULT 0"),
        ("calendar_events", "reminder_minutes", "INTEGER"),
        ("calendar_events", "reminder_sent", "BOOLEAN DEFAULT 0"),
        ("calendar_events", "meeting_notes", "TEXT"),
        ("calendar_events", "transcript_document_id", "VARCHAR(36)"),
        ("calendar_events", "summary_document_id", "VARCHAR(36)"),
        ("calendar_events", "agenda", "TEXT"),
        ("chat_messages", "parent_id", "VARCHAR(36)"),
        ("chat_messages", "thread_count", "INTEGER DEFAULT 0"),
        ("chat_messages", "last_reply_at", "DATETIME"),
        ("chat_messages", "edited_at", "DATETIME"),
        ("chat_messages", "deleted_at", "DATETIME"),
        ("chat_messages", "is_deleted", "BOOLEAN DEFAULT 0"),
        ("chat_messages", "is_pinned", "BOOLEAN DEFAULT 0"),
        ("chat_messages", "pinned_by_id", "VARCHAR(36)"),
        ("chat_messages", "pinned_at", "DATETIME"),
    ]

    for table, column, col_def_sqlite in migrations:
        try:
            if not _table_exists(table):
                continue
            if not _column_exists(table, column):
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {_col_def(col_def_sqlite)}"
                ))
                print(f"  + Added column {table}.{column}")
        except Exception as exc:
            print(f"  ! Could not add {table}.{column}: {exc}")


async def _seed_roles(engine) -> None:
    """Ensure default roles exist before seed scripts run."""
    from src.db.session import get_session_factory, get_async_session
    from src.models.user import Role
    from sqlalchemy import select

    factory = get_session_factory(engine)
    default_roles = [
        Role(name="admin",   description="Full system access"),
        Role(name="analyst", description="Read/write documents and run queries"),
        Role(name="viewer",  description="Read documents and run queries"),
    ]
    async for session in get_async_session(factory):
        for role in default_roles:
            if not (await session.execute(select(Role).where(Role.name == role.name))).scalar_one_or_none():
                session.add(role)
        await session.commit()
    print("Default roles seeded.")


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = get_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("Tables created/verified.")
        await conn.run_sync(_add_missing_columns)
        print("Column migrations applied.")
    await _seed_roles(engine)
    await engine.dispose()
    print("Database initialisation complete.")


if __name__ == "__main__":
    asyncio.run(main())
