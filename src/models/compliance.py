"""Compliance-related DB models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class ComplianceConfig(Base):
    """Single-row table storing system-wide compliance configuration."""

    __tablename__ = "compliance_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="system")
    active_rule_ids: Mapped[list] = mapped_column(JSON, default=list)
    default_action: Mapped[str] = mapped_column(String(20), default="flag")  # allow|flag|block
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ComplianceCollectionOverride(Base):
    """Per-collection compliance rule overrides."""

    __tablename__ = "compliance_collection_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    collection_id: Mapped[str] = mapped_column(String(36), ForeignKey("collections.id"), unique=True, nullable=False)
    active_rule_ids: Mapped[list] = mapped_column(JSON, default=list)
    default_action: Mapped[str] = mapped_column(String(20), default="flag")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class CustomComplianceRuleModel(Base):
    """Admin-defined custom regex/keyword compliance rules."""

    __tablename__ = "custom_compliance_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rule_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(20), nullable=False)  # regex|keyword
    severity: Mapped[str] = mapped_column(String(20), nullable=False)       # critical|high|medium|low
    action: Mapped[str] = mapped_column(String(20), default="flag")         # block|flag|allow
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ComplianceScanResult(Base):
    """Persisted scan records — one per ingestion (or rescan)."""

    __tablename__ = "compliance_scan_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    rules_checked: Mapped[list] = mapped_column(JSON, default=list)
    violations: Mapped[list] = mapped_column(JSON, default=list)
    overall_action: Mapped[str] = mapped_column(String(20), default="allow")  # allow|flag|block
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
