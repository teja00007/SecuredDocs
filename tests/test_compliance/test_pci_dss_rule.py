"""
TDD Test Cases — PCI-DSS Rule (src/compliance/rules/pci_dss_rule.py)

Tests for Payment Card Industry data detection.
"""
import pytest


class TestPciCreditCard:
    """Detect credit card numbers."""

    def test_detects_visa_16_digit(self, pci_rule):
        """Should detect Visa pattern: 4XXX-XXXX-XXXX-XXXX."""
        result = pci_rule.scan("Card on file: 4111111111111111")
        cc_violations = [v for v in result.violations if "card" in v.description.lower()]
        assert len(cc_violations) > 0

    def test_detects_mastercard(self, pci_rule):
        """Should detect Mastercard pattern: 5[1-5]XX-XXXX-XXXX-XXXX."""
        result = pci_rule.scan("Payment method: 5500005555555559")
        cc_violations = [v for v in result.violations if "card" in v.description.lower()]
        assert len(cc_violations) > 0

    def test_detects_amex(self, pci_rule):
        """Should detect Amex pattern: 3[47]XX-XXXXXX-XXXXX."""
        result = pci_rule.scan("Amex card: 378282246310005")
        cc_violations = [v for v in result.violations if "card" in v.description.lower()]
        assert len(cc_violations) > 0

    def test_detects_card_without_dashes(self, pci_rule):
        """Should detect '4111111111111111' (no separators)."""
        result = pci_rule.scan("4111111111111111")
        cc_violations = [v for v in result.violations if "card" in v.description.lower()]
        assert len(cc_violations) > 0

    def test_detects_card_with_spaces(self, pci_rule):
        """Should detect '4111 1111 1111 1111'."""
        result = pci_rule.scan("Card: 4111 1111 1111 1111")
        cc_violations = [v for v in result.violations if "card" in v.description.lower()]
        assert len(cc_violations) > 0

    def test_validates_luhn_checksum(self, pci_rule):
        """Should only flag numbers that pass Luhn algorithm."""
        result_valid = pci_rule.scan("4111111111111111")
        result_invalid = pci_rule.scan("4111111111111112")
        assert len([v for v in result_valid.violations if "card" in v.description.lower()]) > 0
        assert len([v for v in result_invalid.violations if "card" in v.description.lower()]) == 0

    def test_ignores_invalid_luhn(self, pci_rule):
        """16 digits that fail Luhn should NOT be flagged."""
        result = pci_rule.scan("Bad card: 4111111111111112")
        cc_violations = [v for v in result.violations if "card" in v.description.lower()]
        assert len(cc_violations) == 0

    def test_masks_card_in_finding(self, pci_rule):
        """Finding should show '****-****-****-1111'."""
        result = pci_rule.scan("Card: 4111111111111111")
        cc_violations = [v for v in result.violations if "card" in v.description.lower()]
        assert len(cc_violations) > 0
        assert "4111111111" not in cc_violations[0].matched_text
        assert "1111" in cc_violations[0].matched_text

    def test_severity_is_critical(self, pci_rule):
        """Credit card violations should be severity='critical'."""
        result = pci_rule.scan("Card: 4111111111111111")
        cc_violations = [v for v in result.violations if "card" in v.description.lower()]
        assert len(cc_violations) > 0
        assert all(v.severity == "critical" for v in cc_violations)


class TestPciCVV:
    """Detect CVV/CVC codes."""

    def test_detects_cvv_near_card_context(self, pci_rule):
        """'CVV: 123' near a card number should be flagged."""
        result = pci_rule.scan("Card: 4111111111111111 CVV: 123")
        cvv_violations = [v for v in result.violations if "CVV" in v.description or "CVC" in v.description]
        assert len(cvv_violations) > 0

    def test_ignores_3digit_without_context(self, pci_rule):
        """Random 3-digit numbers without card context should NOT be flagged."""
        result = pci_rule.scan("The count is 123 items in stock.")
        cvv_violations = [v for v in result.violations if "CVV" in v.description or "CVC" in v.description]
        assert len(cvv_violations) == 0


class TestPciBankAccount:
    """Detect bank account numbers."""

    def test_detects_routing_number(self, pci_rule):
        """9-digit ABA routing number pattern should be flagged."""
        result = pci_rule.scan("Wire transfer ABA: 123456789")
        routing_violations = [v for v in result.violations if "Routing" in v.description or "routing" in v.description]
        assert len(routing_violations) > 0

    def test_detects_account_number_with_context(self, pci_rule):
        """'Account #: 1234567890' should be flagged."""
        result = pci_rule.scan("Account #: 1234567890")
        acct_violations = [v for v in result.violations if "account" in v.description.lower()]
        assert len(acct_violations) > 0
