"""
TDD Test Cases — Compliance Scanner (src/compliance/scanner.py)

Tests for the compliance scanning orchestrator.
"""
import pytest

from src.compliance.scanner import ComplianceScanner


# ============================================================================
# SCANNER ORCHESTRATION
# ============================================================================

class TestComplianceScanner:
    """ComplianceScanner.scan_sync() — runs all active rules against text."""

    def test_scan_no_active_rules_returns_compliant(self, scanner_no_rules):
        """With no active rules, scan should return is_compliant=True."""
        record = scanner_no_rules.scan_sync("Any text with SSN: 123-45-6789")
        assert not record.has_violations

    def test_scan_clean_text_returns_compliant(self, scanner_with_hipaa, clean_text):
        """Text with no violations should return is_compliant=True."""
        record = scanner_with_hipaa.scan_sync(clean_text)
        assert not record.has_violations

    def test_scan_returns_violations_list(self, scanner_with_hipaa, text_with_ssn):
        """Text with SSN should return is_compliant=False with violations."""
        record = scanner_with_hipaa.scan_sync(text_with_ssn)
        assert record.has_violations
        assert len(record.violations) > 0

    def test_scan_multiple_rules(self, scanner_all_rules, text_with_ssn_and_credit_card):
        """Scanner with HIPAA + PCI-DSS should find violations from both."""
        record = scanner_all_rules.scan_sync(text_with_ssn_and_credit_card)
        rule_names = {v.rule for v in record.violations}
        assert "HIPAA" in rule_names
        assert "PCI-DSS" in rule_names

    def test_scan_records_scanned_rules(self, scanner_with_hipaa):
        """Result.rules_checked should list which rules were checked."""
        record = scanner_with_hipaa.scan_sync("Some text")
        assert "HIPAA" in record.rules_checked

    def test_scan_records_duration(self, scanner_with_hipaa, clean_text):
        """Result.scan_duration_ms should be populated."""
        record = scanner_with_hipaa.scan_sync(clean_text)
        assert hasattr(record, "scan_duration_ms")
        assert record.scan_duration_ms >= 0

    def test_scan_empty_text_returns_compliant(self, scanner_with_hipaa):
        """Empty text should return compliant (nothing to violate)."""
        record = scanner_with_hipaa.scan_sync("")
        assert not record.has_violations

    def test_scan_does_not_store_raw_sensitive_data(self, scanner_with_hipaa, text_with_ssn):
        """Finding.matched_text should be masked, never contain full SSN."""
        record = scanner_with_hipaa.scan_sync(text_with_ssn)
        ssn_violations = [v for v in record.violations if "SSN" in v.description]
        assert len(ssn_violations) > 0
        assert "123-45" not in ssn_violations[0].matched_text


# ============================================================================
# ACTION DECISIONS
# ============================================================================

class TestComplianceActions:
    """Verify the correct action is taken based on config + violation severity."""

    def test_critical_violation_blocks_when_configured(self, scanner_block_critical, text_with_ssn):
        """HIPAA SSN violation (critical) + block_on_critical=True → action='blocked'."""
        record = scanner_block_critical.scan_sync(text_with_ssn)
        assert record.action == "blocked"

    def test_high_violation_flags_when_configured(self, scanner_flag_default, text_with_email):
        """GDPR email violation (high) + default_action='flag' → action='flagged'."""
        record = scanner_flag_default.scan_sync(text_with_email)
        assert record.action == "flagged"

    def test_auto_set_confidential_on_violation(self, scanner_auto_confidential, text_with_ssn):
        """auto_set_confidential=True → document visibility should be set to 'confidential'."""
        record = scanner_auto_confidential.scan_sync(text_with_ssn)
        assert record.visibility == "confidential"

    def test_no_violation_allows(self, scanner_block_critical, clean_text):
        """Clean text → action='allowed', no visibility change."""
        record = scanner_block_critical.scan_sync(clean_text)
        assert not record.has_violations
        assert record.action == "allowed"

    def test_collection_override_takes_precedence(self, scanner_with_collection_override):
        """Collection-specific rules should override system-wide config."""
        record = scanner_with_collection_override.scan_sync(
            "Contact: user@example.com",
            collection_id="col-001",
        )
        rule_names = {v.rule for v in record.violations}
        assert "GDPR" in rule_names
        assert "HIPAA" not in rule_names

    def test_admin_can_override_blocked_document(self, compliance_service, blocked_doc_id):
        """Admin should be able to call override_block on a blocked document."""
        admin_id = "admin-user-uuid-001"
        compliance_service.override_block(blocked_doc_id, admin_id)
        compliance_service.override_block.assert_called_once_with(blocked_doc_id, admin_id)

