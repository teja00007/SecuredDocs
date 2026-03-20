"""Data access layer for compliance models."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.compliance import (
    ComplianceConfig,
    ComplianceCollectionOverride,
    CustomComplianceRuleModel,
    ComplianceScanResult,
)


class ComplianceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── System config ────────────────────────────────────────────────────────

    async def get_config(self) -> ComplianceConfig:
        result = await self._db.execute(select(ComplianceConfig).where(ComplianceConfig.id == "system"))
        cfg = result.scalar_one_or_none()
        if cfg is None:
            # Use upsert to avoid duplicate key error in multi-tenant concurrent init
            stmt = pg_insert(ComplianceConfig).values(
                id="system",
                active_rule_ids=["hipaa", "pci_dss", "gdpr", "sox"],
                default_action="flag",
            ).on_conflict_do_nothing(index_elements=["id"])
            await self._db.execute(stmt)
            await self._db.flush()
            result = await self._db.execute(select(ComplianceConfig).where(ComplianceConfig.id == "system"))
            cfg = result.scalar_one()
        return cfg

    async def update_config(self, active_rule_ids: list[str], default_action: str) -> ComplianceConfig:
        cfg = await self.get_config()
        cfg.active_rule_ids = active_rule_ids
        cfg.default_action = default_action
        await self._db.flush()
        return cfg

    # ── Collection overrides ─────────────────────────────────────────────────

    async def get_collection_override(self, collection_id: str) -> ComplianceCollectionOverride | None:
        result = await self._db.execute(
            select(ComplianceCollectionOverride).where(
                ComplianceCollectionOverride.collection_id == collection_id
            )
        )
        return result.scalar_one_or_none()

    async def upsert_collection_override(
        self, collection_id: str, active_rule_ids: list[str], default_action: str
    ) -> ComplianceCollectionOverride:
        override = await self.get_collection_override(collection_id)
        if override is None:
            override = ComplianceCollectionOverride(
                collection_id=collection_id,
                active_rule_ids=active_rule_ids,
                default_action=default_action,
            )
            self._db.add(override)
        else:
            override.active_rule_ids = active_rule_ids
            override.default_action = default_action
        await self._db.flush()
        return override

    # ── Custom rules ─────────────────────────────────────────────────────────

    async def list_custom_rules(self) -> list[CustomComplianceRuleModel]:
        result = await self._db.execute(select(CustomComplianceRuleModel))
        return list(result.scalars().all())

    async def get_custom_rule_by_rule_id(self, rule_id: str) -> CustomComplianceRuleModel | None:
        result = await self._db.execute(
            select(CustomComplianceRuleModel).where(CustomComplianceRuleModel.rule_id == rule_id)
        )
        return result.scalar_one_or_none()

    async def create_custom_rule(self, rule: CustomComplianceRuleModel) -> CustomComplianceRuleModel:
        self._db.add(rule)
        await self._db.flush()
        return rule

    async def delete_custom_rule(self, rule_id: str) -> bool:
        rule = await self.get_custom_rule_by_rule_id(rule_id)
        if not rule:
            return False
        await self._db.delete(rule)
        await self._db.flush()
        return True

    # ── Scan results ─────────────────────────────────────────────────────────

    async def get_latest_scan(self, document_id: str) -> ComplianceScanResult | None:
        result = await self._db.execute(
            select(ComplianceScanResult)
            .where(ComplianceScanResult.document_id == document_id)
            .order_by(ComplianceScanResult.scanned_at.desc())
        )
        return result.scalars().first()

    async def create_scan_result(self, scan: ComplianceScanResult) -> ComplianceScanResult:
        self._db.add(scan)
        await self._db.flush()
        return scan
