"""SQL Agent — natural language → safe read-only SQL queries.

Architecture:
  1. Introspect the database schema (table names, columns, types).
  2. Send (question + schema) to the LLM, request a SELECT-only query.
  3. Validate the generated SQL is strictly read-only.
  4. Execute and return (columns, rows) capped at MAX_ROWS.
"""

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from src.core.interfaces import ILLM

logger = logging.getLogger(__name__)

MAX_ROWS = 500

# ---------------------------------------------------------------------------
# Tables exposed to the SQL agent (whitelist — never expose credential tables)
# ---------------------------------------------------------------------------
_ALLOWED_TABLES: set[str] = {
    "documents",
    "collections",
    "teams",
    "team_members",
    "users",
    "calendar_events",
    "calendar_attendees",
    "channels",
    "chat_messages",
    "audit_logs",
    "conversation_messages",
    "document_tags",
    "document_versions",
    "document_folders",
}

# SQL tokens that are never allowed — guards against comment-based bypasses
_BANNED_TOKENS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|MERGE"
    r"|EXEC|EXECUTE|CALL|PRAGMA|ATTACH|DETACH|GRANT|REVOKE|COPY)\b",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = """\
You are an expert SQL assistant for the Nexus enterprise knowledge system.
You translate natural-language questions into safe, read-only SQL SELECT queries.

Rules:
1. Only generate SELECT statements. Never use INSERT, UPDATE, DELETE, DROP,
   ALTER, CREATE, EXEC, PRAGMA, or any other mutating statement.
2. Always alias columns for readability.
3. Limit results to {max_rows} rows using LIMIT {max_rows}.
4. Use table/column names exactly as provided in the schema.
5. If the question cannot be answered with a SELECT query, output exactly:
   UNSUPPORTED: <reason>
6. Output only the SQL query — no markdown fences, no explanation.

Database schema:
{schema}
"""


class SQLAgent:
    def __init__(self, llm: ILLM) -> None:
        self._llm = llm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def query(
        self,
        question: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Translate `question` to SQL, execute it, and return results."""
        schema = await self._get_schema(db)
        sql = await self._generate_sql(question, schema)

        if sql.upper().startswith("UNSUPPORTED:"):
            return {
                "sql": None,
                "columns": [],
                "rows": [],
                "error": sql[len("UNSUPPORTED:"):].strip(),
                "row_count": 0,
            }

        error = self._validate_sql(sql)
        if error:
            return {
                "sql": sql,
                "columns": [],
                "rows": [],
                "error": error,
                "row_count": 0,
            }

        return await self._execute(sql, db)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_schema(self, db: AsyncSession) -> str:
        """Introspect DB and return a compact schema string."""
        dialect = db.bind.dialect.name if db.bind else "sqlite"
        lines: list[str] = []

        if dialect == "sqlite":
            result = await db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            )
            tables = [row[0] for row in result.fetchall() if row[0] in _ALLOWED_TABLES]
            for table in tables:
                cols = await db.execute(text(f"PRAGMA table_info({table})"))
                col_defs = ", ".join(
                    f"{row[1]} {row[2]}" for row in cols.fetchall()
                )
                lines.append(f"  {table}({col_defs})")
        else:
            # PostgreSQL
            result = await db.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            ))
            tables = [row[0] for row in result.fetchall() if row[0] in _ALLOWED_TABLES]
            for table in tables:
                cols = await db.execute(text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"
                ), {"t": table})
                col_defs = ", ".join(f"{r[0]} {r[1]}" for r in cols.fetchall())
                lines.append(f"  {table}({col_defs})")

        return "Tables:\n" + "\n".join(lines) if lines else "No accessible tables."

    async def _generate_sql(self, question: str, schema: str) -> str:
        """Ask the LLM to generate a SELECT query."""
        system = _SYSTEM_PROMPT.format(schema=schema, max_rows=MAX_ROWS)
        response = await self._llm.generate(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        return response.content.strip()

    def _validate_sql(self, sql: str) -> str | None:
        """Return an error string if the SQL is not safe, None if OK."""
        # Must start with SELECT
        stripped = sql.lstrip()
        if not stripped.upper().startswith("SELECT"):
            return "Only SELECT queries are allowed."

        # No banned tokens (handles comment-based injection too)
        match = _BANNED_TOKENS.search(sql)
        if match:
            return f"Forbidden SQL token: {match.group()}"

        # No semicolons except at end (prevents multi-statement injection)
        parts = [p.strip() for p in sql.rstrip(";").split(";") if p.strip()]
        if len(parts) > 1:
            return "Multi-statement queries are not allowed."

        return None

    async def _execute(self, sql: str, db: AsyncSession) -> dict[str, Any]:
        """Execute the validated SQL and return columns + rows."""
        try:
            result = await db.execute(text(sql))
            columns = list(result.keys())
            rows = [list(row) for row in result.fetchmany(MAX_ROWS)]
            return {
                "sql": sql,
                "columns": columns,
                "rows": rows,
                "error": None,
                "row_count": len(rows),
            }
        except Exception as exc:
            logger.warning("SQL agent execution error: %s | SQL: %s", exc, sql)
            return {
                "sql": sql,
                "columns": [],
                "rows": [],
                "error": str(exc),
                "row_count": 0,
            }
