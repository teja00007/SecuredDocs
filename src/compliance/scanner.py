"""Compliance scanner — orchestrates rule-based and optional LLM scanning."""

import logging
import time
from dataclasses import dataclass, field

from src.compliance.rules.base import BaseComplianceRule, ScanResult, Violation

logger = logging.getLogger(__name__)


@dataclass
class ComplianceScanRecord:
    document_id: str
    rules_checked: list[str]
    violations: list[Violation] = field(default_factory=list)
    llm_checked: bool = False
    llm_summary: str = ""
    scan_duration_ms: float = 0.0
    action: str = "allowed"        # "allowed" | "flagged" | "blocked"
    visibility: str | None = None  # set when auto_set_confidential triggers

    @property
    def has_critical(self) -> bool:
        return any(v.severity == "critical" for v in self.violations)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0


class ComplianceScanner:
    """Two-stage scanner: regex (fast, sync) + optional LLM (contextual, async)."""

    def __init__(
        self,
        rules: list[BaseComplianceRule] | None = None,
        settings=None,
    ) -> None:
        if rules is not None:
            self._rules = rules
        else:
            self._rules = self._load_default_rules()
        self._settings = settings

    def _load_default_rules(self) -> list[BaseComplianceRule]:
        from src.compliance.rules.hipaa_rule import HipaaRule
        from src.compliance.rules.pci_dss_rule import PciDssRule
        from src.compliance.rules.gdpr_rule import GdprRule
        from src.compliance.rules.sox_rule import SoxRule
        return [HipaaRule(), PciDssRule(), GdprRule(), SoxRule()]

    def _rules_for(self, collection_id: str | None) -> list[BaseComplianceRule]:
        """Return rules, applying collection-level override if configured."""
        if collection_id and self._settings:
            overrides: dict = getattr(self._settings, "COMPLIANCE_COLLECTION_OVERRIDES", {})
            if collection_id in overrides:
                from src.compliance.rule_registry import COMPLIANCE_RULE_REGISTRY
                rule_ids = overrides[collection_id]
                return [
                    COMPLIANCE_RULE_REGISTRY[rid]()
                    for rid in rule_ids
                    if rid in COMPLIANCE_RULE_REGISTRY
                ]
        return self._rules

    def _apply_action(self, record: ComplianceScanRecord) -> None:
        """Populate record.action and record.visibility based on settings."""
        if not self._settings or not record.has_violations:
            return

        if getattr(self._settings, "COMPLIANCE_BLOCK_ON_CRITICAL", False) and record.has_critical:
            record.action = "blocked"
        elif getattr(self._settings, "COMPLIANCE_DEFAULT_ACTION", None) == "flag":
            record.action = "flagged"

        if getattr(self._settings, "COMPLIANCE_AUTO_SET_CONFIDENTIAL", False) and record.has_violations:
            record.visibility = "confidential"

    def register(self, rule: BaseComplianceRule) -> None:
        self._rules.append(rule)

    def scan_sync(
        self,
        text: str,
        document_id: str = "",
        collection_id: str | None = None,
    ) -> ComplianceScanRecord:
        """Stage 1: Fast regex scan. Always synchronous."""
        active_rules = self._rules_for(collection_id)
        record = ComplianceScanRecord(
            document_id=document_id,
            rules_checked=[r.rule_name for r in active_rules],
        )
        t0 = time.perf_counter()
        for rule in active_rules:
            try:
                result = rule.scan(text)
                record.violations.extend(result.violations)
            except Exception as e:
                logger.warning("Rule %s failed: %s", rule.rule_name, e)

        record.scan_duration_ms = (time.perf_counter() - t0) * 1000
        self._apply_action(record)
        return record

    async def scan_with_llm(
        self,
        text: str,
        document_id: str = "",
        llm=None,
        collection_id: str | None = None,
    ) -> ComplianceScanRecord:
        """Stage 1 (regex) + Stage 2 (optional LLM contextual check)."""
        record = self.scan_sync(text, document_id, collection_id)

        if llm is None or self._settings is None:
            return record

        if not getattr(self._settings, "COMPLIANCE_LLM_ENABLED", False):
            return record

        max_len = getattr(self._settings, "COMPLIANCE_LLM_MAX_TEXT_LENGTH", 4000)
        truncated = text[:max_len]

        prompt = (
            "You are a compliance analyst. Review the following text and identify any "
            "sensitive information that may violate HIPAA, PCI-DSS, GDPR, or SOX regulations. "
            "Be concise. If you find nothing suspicious, say 'No additional concerns.'\n\n"
            f"Text:\n{truncated}"
        )

        try:
            response = await llm.generate(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=512,
            )
            record.llm_checked = True
            record.llm_summary = response.content
            self._parse_llm_violations(response.content, record)
        except Exception as e:
            logger.warning("LLM compliance scan failed: %s", e)

        return record

    def _parse_llm_violations(self, content: str, record: ComplianceScanRecord) -> None:
        """Extract structured violations from LLM JSON response and deduplicate."""
        import json
        try:
            # Expect: {"violations": [{"description": "...", "severity": "...", "matched_text": "...", "confidence": 0.9}]}
            data = json.loads(content)
            for item in data.get("violations", []):
                confidence = float(item.get("confidence", 1.0))
                if confidence < 0.7:
                    continue
                matched = item.get("matched_text", "")
                # Skip if regex already found this same text
                if any(v.matched_text == matched for v in record.violations):
                    continue
                record.violations.append(Violation(
                    rule="LLM",
                    severity=item.get("severity", "medium"),
                    description=item.get("description", "LLM contextual finding"),
                    matched_text=matched[:100],
                    confidence=confidence,
                ))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # Non-JSON or unexpected format — ignore LLM parse errors
