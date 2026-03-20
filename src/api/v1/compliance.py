"""Compliance configuration and scan result endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db, require_permission
from src.compliance.rules.custom_rule import CustomComplianceRule
from src.compliance.scanner import ComplianceScanner, ComplianceScanRecord
from src.core.rbac import UserContext
from src.models.compliance import CustomComplianceRuleModel, ComplianceScanResult
from src.repositories.compliance_repository import ComplianceRepository
from src.repositories.document_repository import DocumentRepository
from src.schemas.compliance import (
    CollectionOverrideRequest,
    CollectionOverrideResponse,
    ComplianceConfigResponse,
    ComplianceConfigUpdateRequest,
    CustomRuleCreateRequest,
    CustomRuleResponse,
    RuleInfo,
    ScanResultResponse,
    ViolationResponse,
)

router = APIRouter(prefix="/compliance", tags=["compliance"])

# ── Built-in rule metadata registry ──────────────────────────────────────────

BUILTIN_RULES: dict[str, dict] = {
    "hipaa": {
        "name": "HIPAA",
        "description": "Detects Protected Health Information (PHI): SSN, MRN, ICD codes, DOB",
        "severity": "critical",
    },
    "pci_dss": {
        "name": "PCI-DSS",
        "description": "Detects payment card data: card numbers (Luhn-validated), CVV, bank accounts",
        "severity": "critical",
    },
    "gdpr": {
        "name": "GDPR",
        "description": "Detects EU personal data: email, phone, address, national IDs, IP addresses",
        "severity": "high",
    },
    "sox": {
        "name": "SOX",
        "description": "Detects financial audit data: earnings figures, insider info keywords",
        "severity": "high",
    },
}


def _get_compliance_repo(db: AsyncSession = Depends(get_db)) -> ComplianceRepository:
    return ComplianceRepository(db)


def _get_document_repo(db: AsyncSession = Depends(get_db)) -> DocumentRepository:
    return DocumentRepository(db)


def _require_admin(user: UserContext = Depends(get_current_user)) -> UserContext:
    if "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


# ── List rules ────────────────────────────────────────────────────────────────

@router.get("/rules", response_model=list[RuleInfo])
async def list_rules(
    user: UserContext = Depends(_require_admin),
    compliance_repo: ComplianceRepository = Depends(_get_compliance_repo),
    db: AsyncSession = Depends(get_db),
):
    cfg = await compliance_repo.get_config()
    active_ids = set(cfg.active_rule_ids)
    custom_rules = await compliance_repo.list_custom_rules()

    rules: list[RuleInfo] = []

    for rule_id, meta in BUILTIN_RULES.items():
        rules.append(RuleInfo(
            rule_id=rule_id,
            name=meta["name"],
            description=meta["description"],
            severity=meta["severity"],
            is_active=rule_id in active_ids,
            is_custom=False,
        ))

    for cr in custom_rules:
        rules.append(RuleInfo(
            rule_id=cr.rule_id,
            name=cr.name,
            description=cr.description,
            severity=cr.severity,
            is_active=cr.rule_id in active_ids,
            is_custom=True,
        ))

    await db.commit()
    return rules


# ── System-wide config ────────────────────────────────────────────────────────

@router.get("/config", response_model=ComplianceConfigResponse)
async def get_config(
    user: UserContext = Depends(_require_admin),
    compliance_repo: ComplianceRepository = Depends(_get_compliance_repo),
    db: AsyncSession = Depends(get_db),
):
    cfg = await compliance_repo.get_config()
    await db.commit()
    return ComplianceConfigResponse(
        active_rule_ids=cfg.active_rule_ids,
        default_action=cfg.default_action,
        updated_at=cfg.updated_at,
    )


@router.put("/config", response_model=ComplianceConfigResponse)
async def update_config(
    body: ComplianceConfigUpdateRequest,
    user: UserContext = Depends(_require_admin),
    compliance_repo: ComplianceRepository = Depends(_get_compliance_repo),
    db: AsyncSession = Depends(get_db),
):
    # Validate all rule IDs exist
    custom_rules = await compliance_repo.list_custom_rules()
    valid_ids = set(BUILTIN_RULES.keys()) | {cr.rule_id for cr in custom_rules}
    unknown = [rid for rid in body.active_rule_ids if rid not in valid_ids]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown rule IDs: {unknown}")

    cfg = await compliance_repo.update_config(body.active_rule_ids, body.default_action)
    await db.commit()
    return ComplianceConfigResponse(
        active_rule_ids=cfg.active_rule_ids,
        default_action=cfg.default_action,
        updated_at=cfg.updated_at,
    )


# ── Per-collection overrides ──────────────────────────────────────────────────

@router.put("/collections/{collection_id}/config", response_model=CollectionOverrideResponse)
async def set_collection_override(
    collection_id: str,
    body: CollectionOverrideRequest,
    user: UserContext = Depends(_require_admin),
    compliance_repo: ComplianceRepository = Depends(_get_compliance_repo),
    db: AsyncSession = Depends(get_db),
):
    custom_rules = await compliance_repo.list_custom_rules()
    valid_ids = set(BUILTIN_RULES.keys()) | {cr.rule_id for cr in custom_rules}
    unknown = [rid for rid in body.active_rule_ids if rid not in valid_ids]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown rule IDs: {unknown}")

    override = await compliance_repo.upsert_collection_override(
        collection_id=collection_id,
        active_rule_ids=body.active_rule_ids,
        default_action=body.default_action,
    )
    await db.commit()
    return CollectionOverrideResponse(
        collection_id=override.collection_id,
        active_rule_ids=override.active_rule_ids,
        default_action=override.default_action,
        updated_at=override.updated_at,
    )


# ── Custom rules CRUD ─────────────────────────────────────────────────────────

@router.post("/rules/custom", response_model=CustomRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_rule(
    body: CustomRuleCreateRequest,
    user: UserContext = Depends(_require_admin),
    compliance_repo: ComplianceRepository = Depends(_get_compliance_repo),
    db: AsyncSession = Depends(get_db),
):
    # Validate pattern
    try:
        CustomComplianceRule.validate_pattern(body.pattern, body.pattern_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Duplicate check
    existing = await compliance_repo.get_custom_rule_by_rule_id(body.rule_id)
    if existing:
        raise HTTPException(status_code=400, detail=f"Rule ID '{body.rule_id}' already exists")

    rule = CustomComplianceRuleModel(
        rule_id=body.rule_id,
        name=body.name,
        description=body.description,
        pattern=body.pattern,
        pattern_type=body.pattern_type,
        severity=body.severity,
        action=body.action,
        created_by=user.user_id,
    )
    created = await compliance_repo.create_custom_rule(rule)
    await db.commit()
    return CustomRuleResponse(
        id=created.id,
        rule_id=created.rule_id,
        name=created.name,
        description=created.description,
        pattern=created.pattern,
        pattern_type=created.pattern_type,
        severity=created.severity,
        action=created.action,
        created_by=created.created_by,
        created_at=created.created_at,
    )


@router.delete("/rules/custom/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_rule(
    rule_id: str,
    user: UserContext = Depends(_require_admin),
    compliance_repo: ComplianceRepository = Depends(_get_compliance_repo),
    db: AsyncSession = Depends(get_db),
):
    deleted = await compliance_repo.delete_custom_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Custom rule '{rule_id}' not found")
    await db.commit()


# ── Scan results ──────────────────────────────────────────────────────────────

@router.get("/scans/{document_id}", response_model=ScanResultResponse)
async def get_scan_result(
    document_id: str,
    user: UserContext = Depends(get_current_user),
    compliance_repo: ComplianceRepository = Depends(_get_compliance_repo),
    document_repo: DocumentRepository = Depends(_get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Access check: owner or admin
    if doc.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Access denied")

    scan = await compliance_repo.get_latest_scan(document_id)
    if not scan:
        raise HTTPException(status_code=404, detail="No scan record found for this document")

    await db.commit()
    return _scan_to_response(scan)


@router.post("/rescan/{document_id}", response_model=ScanResultResponse)
async def rescan_document(
    document_id: str,
    user: UserContext = Depends(_require_admin),
    compliance_repo: ComplianceRepository = Depends(_get_compliance_repo),
    document_repo: DocumentRepository = Depends(_get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Load file text
    try:
        with open(doc.file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        raise HTTPException(status_code=500, detail="Cannot read document file for rescan")

    # Build scanner with current active rules
    cfg = await compliance_repo.get_config()
    active_ids = set(cfg.active_rule_ids)
    custom_rules = await compliance_repo.list_custom_rules()
    rules = _build_rules(active_ids, custom_rules)

    scanner = ComplianceScanner(rules=rules)
    record: ComplianceScanRecord = scanner.scan_sync(text, document_id=document_id)

    overall_action = _determine_action(record, cfg.default_action)

    scan = ComplianceScanResult(
        document_id=document_id,
        rules_checked=record.rules_checked,
        violations=[
            {"rule": v.rule, "severity": v.severity, "description": v.description, "matched_text": v.matched_text}
            for v in record.violations
        ],
        overall_action=overall_action,
    )
    created = await compliance_repo.create_scan_result(scan)
    await db.commit()
    return _scan_to_response(created)


@router.post("/unblock/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_document(
    document_id: str,
    user: UserContext = Depends(_require_admin),
    document_repo: DocumentRepository = Depends(_get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status != "compliance_blocked":
        raise HTTPException(status_code=400, detail="Document is not compliance-blocked")

    doc.status = "ready"
    await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_rules(active_ids: set[str], custom_rules: list) -> list:
    from src.compliance.rules.hipaa_rule import HipaaRule
    from src.compliance.rules.pci_dss_rule import PciDssRule
    from src.compliance.rules.gdpr_rule import GdprRule
    from src.compliance.rules.sox_rule import SoxRule

    builtin_map = {
        "hipaa": HipaaRule,
        "pci_dss": PciDssRule,
        "gdpr": GdprRule,
        "sox": SoxRule,
    }
    rules = []
    for rule_id, cls in builtin_map.items():
        if rule_id in active_ids:
            rules.append(cls())
    for cr in custom_rules:
        if cr.rule_id in active_ids:
            rules.append(CustomComplianceRule(
                rule_id=cr.rule_id,
                name=cr.name,
                description=cr.description,
                pattern=cr.pattern,
                pattern_type=cr.pattern_type,
                severity=cr.severity,
            ))
    return rules


def _determine_action(record: ComplianceScanRecord, default_action: str) -> str:
    if not record.has_violations:
        return "allow"
    if record.has_critical:
        return "block"
    return default_action


def _scan_to_response(scan: ComplianceScanResult) -> ScanResultResponse:
    violations = [
        ViolationResponse(
            rule=v["rule"],
            severity=v["severity"],
            description=v["description"],
            matched_text=v.get("matched_text", ""),
        )
        for v in (scan.violations or [])
    ]
    return ScanResultResponse(
        id=scan.id,
        document_id=scan.document_id,
        rules_checked=scan.rules_checked,
        violations=violations,
        overall_action=scan.overall_action,
        scanned_at=scan.scanned_at,
    )
