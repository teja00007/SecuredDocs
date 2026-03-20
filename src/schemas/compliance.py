"""Compliance Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel, Field


# ── Built-in rule metadata ────────────────────────────────────────────────────

class RuleInfo(BaseModel):
    rule_id: str
    name: str
    description: str
    severity: str
    is_active: bool
    is_custom: bool = False


# ── System config ─────────────────────────────────────────────────────────────

class ComplianceConfigResponse(BaseModel):
    active_rule_ids: list[str]
    default_action: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ComplianceConfigUpdateRequest(BaseModel):
    active_rule_ids: list[str]
    default_action: str = Field(default="flag", pattern="^(allow|flag|block)$")


# ── Collection override ───────────────────────────────────────────────────────

class CollectionOverrideRequest(BaseModel):
    active_rule_ids: list[str]
    default_action: str = Field(default="flag", pattern="^(allow|flag|block)$")


class CollectionOverrideResponse(BaseModel):
    collection_id: str
    active_rule_ids: list[str]
    default_action: str
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Custom rules ──────────────────────────────────────────────────────────────

class CustomRuleCreateRequest(BaseModel):
    rule_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9_\-]+$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    pattern: str = Field(..., min_length=1)
    pattern_type: str = Field(..., pattern="^(regex|keyword)$")
    severity: str = Field(..., pattern="^(critical|high|medium|low)$")
    action: str = Field(default="flag", pattern="^(allow|flag|block)$")


class CustomRuleResponse(BaseModel):
    id: str
    rule_id: str
    name: str
    description: str
    pattern: str
    pattern_type: str
    severity: str
    action: str
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Scan results ──────────────────────────────────────────────────────────────

class ViolationResponse(BaseModel):
    rule: str
    severity: str
    description: str
    matched_text: str


class ScanResultResponse(BaseModel):
    id: str
    document_id: str
    rules_checked: list[str]
    violations: list[ViolationResponse]
    overall_action: str
    scanned_at: datetime

    model_config = {"from_attributes": True}
