"""License and plan model."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base

PLAN_LIMITS = {
    "free":       {"max_users": 3,  "max_storage_gb": 1,   "features": ["ollama_only"]},
    "starter":    {"max_users": 10, "max_storage_gb": 10,  "features": ["cloud_llm", "sso_google", "api_keys", "webhooks"]},
    "team":       {"max_users": 25, "max_storage_gb": 50,  "features": ["cloud_llm", "saml_sso", "eval_dashboard", "connectors", "webhooks", "mcp"]},
    "business":   {"max_users": 75, "max_storage_gb": 200, "features": ["cloud_llm", "saml_sso", "eval_dashboard", "connectors", "custom_branding", "data_export", "audit_export"]},
    "enterprise": {"max_users": -1, "max_storage_gb": -1,  "features": ["all"]},
}

PLAN_PRICES = {
    "free": 0,
    "starter": 20,
    "team": 49,
    "business": 149,
    "enterprise": 399,
}


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    organization: Mapped[str] = mapped_column(String(255), nullable=False)
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)
    max_users: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_storage_gb: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    features_json: Mapped[str] = mapped_column(String(1024), default="[]", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def features(self) -> list[str]:
        try:
            return json.loads(self.features_json)
        except Exception:
            return []

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at < datetime.now(timezone.utc)

    @property
    def is_valid(self) -> bool:
        return self.is_active and not self.is_expired

    def has_feature(self, feature: str) -> bool:
        feats = self.features
        return "all" in feats or feature in feats

    def __repr__(self) -> str:
        return f"<License plan={self.plan} org={self.organization}>"
