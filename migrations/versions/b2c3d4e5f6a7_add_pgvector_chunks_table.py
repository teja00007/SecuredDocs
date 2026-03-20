"""add_pgvector_chunks_table

Revision ID: b2c3d4e5f6a7
Revises: 36cb047d3766
Create Date: 2026-03-17 12:00:00.000000

Creates the document_chunks table used by the PgVectorStore implementation.
Requires the pgvector extension to be available on the PostgreSQL server
(available via pgvector/pgvector Docker image or the pgvector apt/brew package).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "36cb047d3766"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The embedding dimension stored in this table.  Must match EMBEDDING_DIMENSIONS
# in config.py (default 768).  If you need a different dimension, change this
# constant and regenerate the migration.
_EMBEDDING_DIMENSIONS = 768
_TABLE = "document_chunks"


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Enable pgvector extension (no-op if already installed) ────────────
    # We catch any error so that the migration does not fail on databases where
    # the extension cannot be installed (e.g. during CI against plain SQLite).
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))
    except Exception:
        # pgvector not available — skip table creation so other migrations
        # can still run.  The application will raise at startup if pgvector
        # store type is selected without the extension.
        return

    # ── 2. Create document_chunks table (idempotent) ─────────────────────────
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if _TABLE not in existing_tables:
        # We use raw DDL for the vector column type because SQLAlchemy's type
        # system does not know about it natively.
        conn.execute(sa.text(f"""
            CREATE TABLE {_TABLE} (
                id          TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                text        TEXT NOT NULL,
                embedding   vector({_EMBEDDING_DIMENSIONS}) NOT NULL,
                metadata    JSONB NOT NULL DEFAULT '{{}}',
                created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            );
        """))

        # ── 3. Indexes ────────────────────────────────────────────────────────

        # B-tree index for fast document-scoped queries/deletes.
        conn.execute(sa.text(f"""
            CREATE INDEX idx_{_TABLE}_document_id
            ON {_TABLE} (document_id);
        """))

        # GIN index to accelerate JSONB metadata equality / containment queries.
        conn.execute(sa.text(f"""
            CREATE INDEX idx_{_TABLE}_metadata
            ON {_TABLE} USING GIN (metadata);
        """))

        # HNSW index for approximate nearest-neighbour cosine search.
        # This is the primary performance lever for vector retrieval.
        conn.execute(sa.text(f"""
            CREATE INDEX idx_{_TABLE}_embedding_hnsw
            ON {_TABLE} USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if _TABLE in existing_tables:
        # Drop indexes explicitly before dropping the table so that the
        # operation is unambiguous even if CASCADE behaviour differs.
        conn.execute(sa.text(f"DROP INDEX IF EXISTS idx_{_TABLE}_embedding_hnsw;"))
        conn.execute(sa.text(f"DROP INDEX IF EXISTS idx_{_TABLE}_metadata;"))
        conn.execute(sa.text(f"DROP INDEX IF EXISTS idx_{_TABLE}_document_id;"))
        conn.execute(sa.text(f"DROP TABLE {_TABLE};"))
