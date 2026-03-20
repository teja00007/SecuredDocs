"""
TDD Test Cases — Compliance Rule Registry (src/compliance/rule_registry.py)

Tests for the pluggable rule registration system.
"""
import pytest

from src.compliance.rule_registry import (
    COMPLIANCE_RULE_REGISTRY,
    register_rule,
    list_available_rules,
    get_active_rules,
)


class TestRuleRegistry:
    """Verify rule registration and lookup."""

    def test_hipaa_registered(self):
        """COMPLIANCE_RULE_REGISTRY should contain 'hipaa'."""
        assert "hipaa" in COMPLIANCE_RULE_REGISTRY

    def test_pci_dss_registered(self):
        """COMPLIANCE_RULE_REGISTRY should contain 'pci_dss'."""
        assert "pci_dss" in COMPLIANCE_RULE_REGISTRY

    def test_gdpr_registered(self):
        """COMPLIANCE_RULE_REGISTRY should contain 'gdpr'."""
        assert "gdpr" in COMPLIANCE_RULE_REGISTRY

    def test_sox_registered(self):
        """COMPLIANCE_RULE_REGISTRY should contain 'sox'."""
        assert "sox" in COMPLIANCE_RULE_REGISTRY

    def test_register_custom_rule(self):
        """Registering a new rule class should add it to the registry."""
        from src.compliance.rules.base import BaseComplianceRule, ScanResult

        class DummyRule(BaseComplianceRule):
            @property
            def rule_name(self):
                return "DUMMY_TEST"

            def scan(self, text):
                return ScanResult(rule_name=self.rule_name)

        register_rule("dummy_test", DummyRule)
        assert "dummy_test" in COMPLIANCE_RULE_REGISTRY
        # Cleanup to avoid polluting other tests
        del COMPLIANCE_RULE_REGISTRY["dummy_test"]

    def test_list_available_rules(self):
        """list_available_rules() should return metadata for all registered rules."""
        rules = list_available_rules()
        assert isinstance(rules, list)
        assert len(rules) >= 4
        rule_ids = [r["id"] for r in rules]
        assert "hipaa" in rule_ids
        assert "pci_dss" in rule_ids
        assert "gdpr" in rule_ids
        assert "sox" in rule_ids
        # Each entry should have id and name
        for r in rules:
            assert "id" in r
            assert "name" in r

    def test_get_active_rules_from_config(self, system_config_hipaa_pci):
        """get_active_rules() with config ['hipaa', 'pci_dss'] should return 2 rule instances."""
        rules = get_active_rules(system_config_hipaa_pci)
        assert len(rules) == 2
        rule_names = {r.rule_name for r in rules}
        assert "HIPAA" in rule_names
        assert "PCI-DSS" in rule_names

    def test_get_active_rules_empty_config(self):
        """Empty active_rule_ids should return empty list."""
        class EmptyConfig:
            active_rule_ids = []

        rules = get_active_rules(EmptyConfig())
        assert rules == []

    def test_get_active_rules_with_collection_override(self, collection_override):
        """Collection override should replace system-wide rules."""
        rules = get_active_rules(collection_override)
        assert len(rules) == 1
        assert rules[0].rule_name == "GDPR"

    def test_unknown_rule_id_ignored(self):
        """Config with unknown rule_id should skip it (not crash)."""
        class BadConfig:
            active_rule_ids = ["hipaa", "nonexistent_rule_xyz"]

        rules = get_active_rules(BadConfig())
        # Should only return the known rule
        assert len(rules) == 1
        assert rules[0].rule_name == "HIPAA"


class TestCustomRules:
    """Verify admin-defined custom compliance rules."""

    def test_custom_regex_rule_detects_pattern(self, custom_regex_rule):
        """Custom rule with regex should detect the CONFIDENTIAL keyword."""
        result = custom_regex_rule.scan("This is a CONFIDENTIAL document.")
        assert len(result.violations) > 0
        assert any("Confidential" in v.description for v in result.violations)

    def test_custom_keyword_rule_detects_words(self, custom_keyword_rule):
        """Custom keyword rule should detect the configured keyword."""
        result = custom_keyword_rule.scan("This project is a secret initiative.")
        assert len(result.violations) > 0

    def test_custom_rule_case_insensitive(self, custom_keyword_rule):
        """Keyword matching should be case-insensitive."""
        result = custom_keyword_rule.scan("This project is SECRET.")
        assert len(result.violations) > 0

    def test_custom_regex_validates_on_creation(self):
        """Invalid regex should raise ValueError on rule creation."""
        from src.compliance.rules.base import BaseComplianceRule, ScanResult

        class InvalidRegexRule(BaseComplianceRule):
            @property
            def rule_name(self):
                return "INVALID"

            def scan(self, text):
                return ScanResult(rule_name=self.rule_name)

        with pytest.raises(ValueError):
            InvalidRegexRule(pattern="[invalid(regex")

    def test_custom_regex_rejects_catastrophic_backtracking(self):
        """Regex patterns prone to ReDoS should be rejected."""
        from src.compliance.rules.base import BaseComplianceRule, ScanResult

        class ReDoSRule(BaseComplianceRule):
            @property
            def rule_name(self):
                return "REDOS"

            def scan(self, text):
                return ScanResult(rule_name=self.rule_name)

        with pytest.raises(ValueError, match="catastrophic backtracking"):
            ReDoSRule(pattern="(a+)+b")
