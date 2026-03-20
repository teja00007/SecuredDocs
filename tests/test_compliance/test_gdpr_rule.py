"""
TDD Test Cases — GDPR Rule (src/compliance/rules/gdpr_rule.py)

Tests for EU personal data detection.
"""
import pytest


class TestGdprEmail:
    """Detect email addresses (PII)."""

    def test_detects_standard_email(self, gdpr_rule):
        """Should detect 'user@example.com'."""
        result = gdpr_rule.scan("Contact: user@example.com")
        email_violations = [v for v in result.violations if "Email" in v.description]
        assert len(email_violations) > 0

    def test_detects_email_in_text(self, gdpr_rule):
        """Should detect email embedded in paragraph text."""
        result = gdpr_rule.scan(
            "Please send your invoice to accounts.payable@acmecorp.co.uk before the deadline."
        )
        email_violations = [v for v in result.violations if "Email" in v.description]
        assert len(email_violations) > 0

    def test_ignores_example_emails(self, gdpr_rule):
        """'user@example.com' in documentation context should still flag (it's a pattern)."""
        result = gdpr_rule.scan("Example: user@example.com shows the email field format.")
        email_violations = [v for v in result.violations if "Email" in v.description]
        assert len(email_violations) > 0

    def test_severity_is_high(self, gdpr_rule):
        """Email PII should be severity='high'."""
        result = gdpr_rule.scan("Reach out to alice@company.com for details.")
        email_violations = [v for v in result.violations if "Email" in v.description]
        assert len(email_violations) > 0
        assert all(v.severity == "high" for v in email_violations)


class TestGdprPhone:
    """Detect phone numbers."""

    def test_detects_international_format(self, gdpr_rule):
        """Should detect '+44 20 7946 0958'."""
        result = gdpr_rule.scan("Call us at +44 20 7946 0958")
        phone_violations = [v for v in result.violations if "Phone" in v.description]
        assert len(phone_violations) > 0

    def test_detects_eu_national_formats(self, gdpr_rule):
        """Should detect common EU formats (DE, FR, IT, ES, etc.)."""
        result = gdpr_rule.scan("German office: +49 170 1234567")
        phone_violations = [v for v in result.violations if "Phone" in v.description]
        assert len(phone_violations) > 0

    def test_ignores_non_phone_numbers(self, gdpr_rule):
        """Random number sequences should NOT be flagged."""
        result = gdpr_rule.scan("Invoice 42 processed. Quantity: 5.")
        phone_violations = [v for v in result.violations if "Phone" in v.description]
        assert len(phone_violations) == 0


class TestGdprAddress:
    """Detect physical addresses."""

    def test_detects_address_with_postal_code(self, gdpr_rule):
        """Should detect structured addresses with EU postal codes."""
        result = gdpr_rule.scan("Musterstraße 1, 10115 Berlin, Germany")
        postcode_violations = [v for v in result.violations if "postcode" in v.description.lower() or "postal" in v.description.lower()]
        assert len(postcode_violations) > 0

    def test_detects_uk_postcode(self, gdpr_rule):
        """Should detect UK format 'SW1A 1AA'."""
        result = gdpr_rule.scan("Send to 10 Downing Street, SW1A 1AA, London.")
        postcode_violations = [v for v in result.violations if "postcode" in v.description.lower() or "UK" in v.description]
        assert len(postcode_violations) > 0


class TestGdprNationalID:
    """Detect national ID numbers."""

    def test_detects_uk_nin(self, gdpr_rule):
        """UK National Insurance Number: 'AB 12 34 56 C'."""
        result = gdpr_rule.scan("NI Number: AB 12 34 56 C")
        id_violations = [v for v in result.violations if "National" in v.description or "Insurance" in v.description]
        assert len(id_violations) > 0

    def test_masks_id_in_finding(self, gdpr_rule):
        """Finding should mask the ID number."""
        result = gdpr_rule.scan("Passport: AB1234567")
        id_violations = [v for v in result.violations if "National" in v.description or "ID" in v.description]
        assert len(id_violations) > 0
        assert "AB1234567" not in id_violations[0].matched_text


class TestGdprIPAddress:
    """Detect IP addresses (personal data under GDPR)."""

    def test_detects_ipv4(self, gdpr_rule):
        """Should detect '192.168.1.100'."""
        result = gdpr_rule.scan("User connected from 192.168.1.100")
        ip_violations = [v for v in result.violations if "IP" in v.description]
        assert len(ip_violations) > 0

    def test_detects_ipv6(self, gdpr_rule):
        """Should detect IPv6 addresses."""
        result = gdpr_rule.scan("IPv6 source: 2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        ip_violations = [v for v in result.violations if "IP" in v.description]
        assert len(ip_violations) > 0

    def test_ignores_private_ranges_option(self, gdpr_rule):
        """Private IPs (10.x, 192.168.x) are currently detected — no exclusion option yet."""
        result = gdpr_rule.scan("Internal server at 10.0.0.1")
        ip_violations = [v for v in result.violations if "IP" in v.description]
        assert len(ip_violations) > 0
