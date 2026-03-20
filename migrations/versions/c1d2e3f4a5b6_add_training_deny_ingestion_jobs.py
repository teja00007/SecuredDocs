"""add training_examples, document_deny_list, service_accounts, ingestion_jobs

Revision ID: c1d2e3f4a5b6
Revises: 36cb047d3766
Create Date: 2026-03-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "36cb047d3766"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = inspector.get_table_names()

    # ── ingestion_jobs ────────────────────────────────────────────────────────
    if "ingestion_jobs" not in existing:
        op.create_table(
            "ingestion_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("triggered_by", sa.String(36), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending", index=True),
            sa.Column("progress_pct", sa.Float, nullable=False, server_default="0.0"),
            sa.Column("total_chunks", sa.Integer, nullable=False, server_default="0"),
            sa.Column("processed_chunks", sa.Integer, nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )

    # ── document_deny_list ────────────────────────────────────────────────────
    if "document_deny_list" not in existing:
        op.create_table(
            "document_deny_list",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("reason", sa.String(500), nullable=True),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("document_id", "user_id", "team_id", name="uq_deny_entry"),
        )

    # ── service_accounts ──────────────────────────────────────────────────────
    if "service_accounts" not in existing:
        op.create_table(
            "service_accounts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.String(500), nullable=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("roles", sa.String(500), nullable=False, server_default="ingestion"),
            sa.Column("hashed_api_key", sa.String(255), nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
            sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("company_id", "name", name="uq_service_account_name"),
        )

    # ── training_examples ─────────────────────────────────────────────────────
    if "training_examples" not in existing:
        op.create_table(
            "training_examples",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("query", sa.Text, nullable=False),
            sa.Column("answer", sa.Text, nullable=False),
            sa.Column("context", sa.Text, nullable=True),
            sa.Column("system_prompt", sa.Text, nullable=True),
            sa.Column("model_name", sa.String(128), nullable=True),
            sa.Column("feedback", sa.String(32), nullable=False, server_default="neutral", index=True),
            sa.Column("corrected_answer", sa.Text, nullable=True),
            sa.Column("confidence_score", sa.Float, nullable=True),
            sa.Column("rated_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True),
            sa.Column("approved_for_training", sa.Boolean, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        )


def downgrade() -> None:
    for table in ("training_examples", "service_accounts", "document_deny_list", "ingestion_jobs"):
        try:
            op.drop_table(table)
        except Exception:
            pass
