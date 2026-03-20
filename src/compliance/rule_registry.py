"""Compliance rule registry — central lookup for all registered rules."""

from src.compliance.rules.base import BaseComplianceRule


# Registry: rule_id → rule class
COMPLIANCE_RULE_REGISTRY: dict[str, type[BaseComplianceRule]] = {}


def register_rule(rule_id: str, rule_class: type[BaseComplianceRule]) -> None:
    """Register a compliance rule class under the given ID."""
    COMPLIANCE_RULE_REGISTRY[rule_id] = rule_class


def list_available_rules() -> list[dict]:
    """Return metadata for all registered rules."""
    return [
        {"id": rule_id, "name": cls().rule_name}
        for rule_id, cls in COMPLIANCE_RULE_REGISTRY.items()
    ]


def get_active_rules(config) -> list[BaseComplianceRule]:
    """Instantiate and return rules listed in config.active_rule_ids."""
    active_ids: list[str] = getattr(config, "active_rule_ids", [])
    rules = []
    for rule_id in active_ids:
        cls = COMPLIANCE_RULE_REGISTRY.get(rule_id)
        if cls is not None:
            rules.append(cls())
    return rules


# ── Auto-register built-in rules ─────────────────────────────────────────────

def _bootstrap() -> None:
    from src.compliance.rules.hipaa_rule import HipaaRule
    from src.compliance.rules.pci_dss_rule import PciDssRule
    from src.compliance.rules.gdpr_rule import GdprRule
    from src.compliance.rules.sox_rule import SoxRule

    register_rule("hipaa", HipaaRule)
    register_rule("pci_dss", PciDssRule)
    register_rule("gdpr", GdprRule)
    register_rule("sox", SoxRule)


_bootstrap()
