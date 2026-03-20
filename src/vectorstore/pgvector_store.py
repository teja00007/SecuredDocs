"""PostgreSQL + pgvector vector store implementation.

Uses asyncpg for async PostgreSQL connections.
Requires: pip install pgvector asyncpg

Start PostgreSQL with pgvector:
    docker run -e POSTGRES_PASSWORD=postgres -p 5432:5432 pgvector/pgvector:pg16

Set VECTOR_STORE_TYPE=pgvector and DATABASE_URL=postgresql://... in .env.
"""

import json
import logging
import uuid
from typing import Any

from src.core.exceptions import VectorStoreError
from src.core.interfaces import IVectorStore, ChunkResult

logger = logging.getLogger(__name__)

try:
    import asyncpg
    from pgvector.asyncpg import register_vector
    _PGVECTOR_AVAILABLE = True
except ImportError:
    _PGVECTOR_AVAILABLE = False


class PgVectorStore(IVectorStore):
    """PostgreSQL + pgvector backed vector store with RBAC metadata filtering.

    Stores chunks in a single ``document_chunks`` table. Metadata is stored as
    a JSONB column so that arbitrary keys can be queried without schema changes.
    An HNSW index on the embedding column provides fast approximate nearest-
    neighbour search with cosine distance.
    """

    def __init__(
        self,
        connection_string: str,
        dimensions: int = 768,
        table_name: str = "document_chunks",
    ) -> None:
        if not _PGVECTOR_AVAILABLE:
            raise VectorStoreError(
                "pgvector and/or asyncpg is not installed. "
                "Run: pip install pgvector asyncpg"
            )
        # asyncpg uses the postgresql:// scheme; strip SQLAlchemy driver prefixes.
        self._dsn = self._normalise_dsn(connection_string)
        self._dimensions = dimensions
        self._table = table_name
        self._pool: "asyncpg.Pool | None" = None

    # ── DSN helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_dsn(dsn: str) -> str:
        """Convert SQLAlchemy-style DSN to a plain asyncpg DSN."""
        # e.g. "postgresql+asyncpg://..." → "postgresql://..."
        for prefix in ("postgresql+asyncpg", "postgres+asyncpg", "postgresql+psycopg2"):
            if dsn.startswith(prefix):
                dsn = "postgresql" + dsn[len(prefix):]
                break
        # "postgres://" → "postgresql://"
        if dsn.startswith("postgres://"):
            dsn = "postgresql://" + dsn[len("postgres://"):]
        return dsn

    # ── Connection pool ───────────────────────────────────────────────────────

    async def _get_pool(self) -> "asyncpg.Pool":
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=self._dsn,
                    min_size=1,
                    max_size=10,
                    init=self._init_connection,
                )
                await self._ensure_table()
            except Exception as e:
                self._pool = None
                raise VectorStoreError(f"Failed to connect to PostgreSQL: {e}")
        return self._pool

    @staticmethod
    async def _init_connection(conn: "asyncpg.Connection") -> None:
        """Register the pgvector codec for every new connection in the pool."""
        await register_vector(conn)

    # ── Schema bootstrap ──────────────────────────────────────────────────────

    async def _ensure_table(self) -> None:
        """Create the document_chunks table and indexes if they don't exist."""
        pool = self._pool
        async with pool.acquire() as conn:
            # Ensure the pgvector extension is available.
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Create the table (idempotent).
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    id          TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    text        TEXT NOT NULL,
                    embedding   vector({self._dimensions}) NOT NULL,
                    metadata    JSONB NOT NULL DEFAULT '{{}}',
                    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
                );
            """)

            # Index for fast document-level lookups and deletes.
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._table}_document_id
                ON {self._table} (document_id);
            """)

            # JSONB GIN index for metadata equality / containment filters.
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._table}_metadata
                ON {self._table} USING GIN (metadata);
            """)

            # HNSW index for approximate nearest-neighbour cosine search.
            # Only create it when the table is empty or on first use; it is a
            # no-op if it already exists.
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self._table}_embedding_hnsw
                ON {self._table} USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """)

    # ── IVectorStore interface ────────────────────────────────────────────────

    async def insert(self, chunks: list[dict]) -> None:
        """Upsert a batch of chunks into the vector store."""
        if not chunks:
            return
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                # Build list of row tuples for executemany.
                rows: list[tuple[Any, ...]] = []
                for chunk in chunks:
                    chunk_id = chunk.get("chunk_id") or str(uuid.uuid4())
                    document_id = chunk.get("document_id", "")
                    text = chunk.get("text", "")
                    embedding = chunk.get("embedding", [])
                    # Everything that isn't a top-level structural key is metadata.
                    meta = {
                        k: v
                        for k, v in chunk.items()
                        if k not in ("chunk_id", "document_id", "text", "embedding")
                    }
                    # Merge explicit "metadata" sub-dict if present.
                    if "metadata" in chunk and isinstance(chunk["metadata"], dict):
                        meta = {**meta, **chunk["metadata"]}
                        meta.pop("metadata", None)
                    rows.append((chunk_id, document_id, text, embedding, json.dumps(meta)))

                await conn.executemany(
                    f"""
                    INSERT INTO {self._table} (id, document_id, text, embedding, metadata)
                    VALUES ($1, $2, $3, $4::vector, $5::jsonb)
                    ON CONFLICT (id) DO UPDATE
                        SET document_id = EXCLUDED.document_id,
                            text        = EXCLUDED.text,
                            embedding   = EXCLUDED.embedding,
                            metadata    = EXCLUDED.metadata;
                    """,
                    rows,
                )
        except VectorStoreError:
            raise
        except Exception as e:
            raise VectorStoreError(f"PgVector insert failed: {e}")

    async def search(
        self, embedding: list[float], filter: dict, top_k: int = 5
    ) -> list[ChunkResult]:
        """Return the top_k most similar chunks, filtered by RBAC metadata."""
        pool = await self._get_pool()
        try:
            where_sql, params = self._build_where(filter)
            # Embedding placeholder comes after filter params.
            emb_idx = len(params) + 1
            topk_idx = emb_idx + 1

            query = f"""
                SELECT
                    id,
                    document_id,
                    text,
                    metadata,
                    1 - (embedding <=> ${emb_idx}::vector) AS score
                FROM {self._table}
                {where_sql}
                ORDER BY embedding <=> ${emb_idx}::vector
                LIMIT ${topk_idx};
            """
            params.append(embedding)
            params.append(top_k)

            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)

            results: list[ChunkResult] = []
            for row in rows:
                meta = row["metadata"]
                if isinstance(meta, str):
                    meta = json.loads(meta)
                results.append(ChunkResult(
                    chunk_id=row["id"],
                    document_id=row["document_id"],
                    text=row["text"],
                    metadata=meta,
                    score=float(row["score"]),
                ))
            return results
        except VectorStoreError:
            raise
        except Exception as e:
            raise VectorStoreError(f"PgVector search failed: {e}")

    async def delete_by_document_id(self, document_id: str) -> int:
        """Delete all chunks belonging to a document. Returns deleted count."""
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    f"DELETE FROM {self._table} WHERE document_id = $1;",
                    document_id,
                )
            # asyncpg returns e.g. "DELETE 3"
            parts = result.split()
            return int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0
        except Exception as e:
            raise VectorStoreError(f"PgVector delete failed: {e}")

    async def update_metadata(self, document_id: str, metadata: dict) -> None:
        """Merge new metadata key/values into all chunks for a document."""
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    f"""
                    UPDATE {self._table}
                    SET metadata = metadata || $2::jsonb
                    WHERE document_id = $1;
                    """,
                    document_id,
                    json.dumps(metadata),
                )
        except Exception as e:
            raise VectorStoreError(f"PgVector update_metadata failed: {e}")

    async def count(self) -> int:
        """Return total number of chunks stored."""
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(f"SELECT COUNT(*) AS n FROM {self._table};")
            return int(row["n"])
        except Exception as e:
            raise VectorStoreError(f"PgVector count failed: {e}")

    # ── Filter translation ────────────────────────────────────────────────────

    def _build_where(self, filter: dict) -> tuple[str, list[Any]]:
        """Translate a generic RBAC filter dict into a SQL WHERE clause.

        Returns a ``(where_sql, params)`` tuple where ``where_sql`` is either
        empty string or starts with ``WHERE``, and ``params`` is the
        positional parameter list (to be extended with the embedding vector).

        The filter dict can contain:
        - ``visibility``: exact match on ``metadata->>'visibility'``
        - ``owner_id``: exact match on ``metadata->>'owner_id'``
        - ``collection_id``: exact match on ``metadata->>'collection_id'``
        - ``allowed_teams``: list — chunk's teams array must overlap
        - ``$or``: list of sub-filter dicts (RBAC visibility union)
        - ``$and``: list of sub-filter dicts (conjunctive)
        """
        if not filter:
            return "", []

        params: list[Any] = []
        sql = self._filter_to_sql(filter, params)
        if not sql:
            return "", []
        return f"WHERE {sql}", params

    def _filter_to_sql(self, filt: dict, params: list[Any]) -> str:
        """Recursively translate a filter dict to a SQL boolean expression."""
        or_clauses = filt.get("$or")
        and_clauses = filt.get("$and")

        if or_clauses:
            parts = [self._filter_to_sql(c, params) for c in or_clauses]
            parts = [p for p in parts if p]
            if not parts:
                return ""
            return "(" + " OR ".join(parts) + ")"

        if and_clauses:
            parts = [self._filter_to_sql(c, params) for c in and_clauses]
            parts = [p for p in parts if p]
            if not parts:
                return ""
            return "(" + " AND ".join(parts) + ")"

        # Leaf clause — translate individual keys.
        conditions: list[str] = []
        for key, value in filt.items():
            if key in ("$or", "$and"):
                continue
            if key == "visibility":
                idx = len(params) + 1
                params.append(str(value))
                conditions.append(f"metadata->>'visibility' = ${idx}")
            elif key == "owner_id":
                idx = len(params) + 1
                params.append(str(value))
                conditions.append(f"metadata->>'owner_id' = ${idx}")
            elif key == "collection_id":
                # Value may be a raw string or {"$eq": str}
                raw = value["$eq"] if isinstance(value, dict) and "$eq" in value else value
                idx = len(params) + 1
                params.append(str(raw))
                conditions.append(f"metadata->>'collection_id' = ${idx}")
            elif key == "allowed_teams" and isinstance(value, list) and value:
                # Chunk's metadata->allowed_teams must contain at least one team id.
                # Stored as a JSONB array; use the ?| (has any key) operator on an
                # array cast, or a plain jsonb @> containment check per element.
                # We build: (metadata->'allowed_teams' @> $n OR ...)
                or_parts: list[str] = []
                for tid in value:
                    idx = len(params) + 1
                    params.append(json.dumps([tid]))
                    or_parts.append(f"metadata->'allowed_teams' @> ${idx}::jsonb")
                if or_parts:
                    conditions.append("(" + " OR ".join(or_parts) + ")")
            elif key == "allowed_users" and isinstance(value, list) and value:
                or_parts = []
                for uid in value:
                    idx = len(params) + 1
                    params.append(json.dumps([uid]))
                    or_parts.append(f"metadata->'allowed_users' @> ${idx}::jsonb")
                if or_parts:
                    conditions.append("(" + " OR ".join(or_parts) + ")")
            else:
                # Generic equality — treat as a JSONB text field match.
                if isinstance(value, dict) and "$eq" in value:
                    value = value["$eq"]
                if isinstance(value, str):
                    idx = len(params) + 1
                    params.append(value)
                    conditions.append(f"metadata->>{key!r} = ${idx}")

        if not conditions:
            return ""
        if len(conditions) == 1:
            return conditions[0]
        return "(" + " AND ".join(conditions) + ")"
