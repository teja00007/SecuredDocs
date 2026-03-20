"""GDPR compliance rule — detects personal data (EU residents)."""

import re

from src.compliance.rules.base import BaseComplianceRule, ScanResult, Violation


def _mask_id(text: str) -> str:
    """Mask all but last 3 characters of an ID."""
    if len(text) <= 3:
        return "***"
    return "*" * (len(text) - 3) + text[-3:]


_PATTERNS = [
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "high", "Email address"),
    # EU phone numbers — international format (+3x through +7x), no leading \b before +
    (re.compile(r"(?<!\d)\+(?:3[0-9]|4[0-9]|5[0-9]|6[0-9]|7[0-9])[\s\-]?(?:\d[\s\-]?){6,13}\d"), "high", "Phone number (EU)"),
    # US phone numbers
    (re.compile(r"\b(?:\+1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"), "medium", "Phone number (US)"),
    # IPv4 addresses
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "medium", "IP address (IPv4)"),
    # IPv6 addresses (full and compressed forms)
    (re.compile(
        r"(?<![:\w])"
        r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"           # full
        r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:"                         # ends with ::
        r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}"        # one :: in middle
        r"|::(?:[0-9A-Fa-f]{1,4}:){0,5}[0-9A-Fa-f]{1,4}"       # starts with ::
        r"|::1"                                                   # loopback
    ), "medium", "IP address (IPv6)"),
    # UK National Insurance Number: AB 12 34 56 C
    (re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s*\d{2}\s*\d{2}\s*\d{2}\s*[A-D]\b", re.IGNORECASE), "high", "UK National Insurance Number"),
    # National ID / passport numbers (generic letter+digit format)
    (re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"), "high", "National ID / passport number"),
    # UK postcodes
    (re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b"), "low", "UK postcode"),
    # EU postal codes: German (5 digits), French (5), Italian (5), Spanish (5), Dutch (4+2)
    (re.compile(r"(?<!\d)\d{5}(?!\d)(?=\s+[A-Z])"), "low", "EU postal code (5-digit)"),
    (re.compile(r"\b\d{4}\s?[A-Z]{2}\b"), "low", "EU postal code (NL format)"),
]

# Which descriptions should have their matched_text masked
_MASK_DESCRIPTIONS = {"UK National Insurance Number", "National ID / passport number"}


class GdprRule(BaseComplianceRule):
    @property
    def rule_name(self) -> str:
        return "GDPR"

    def scan(self, text: str) -> ScanResult:
        result = ScanResult(rule_name=self.rule_name)
        for pattern, severity, description in _PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group()
                if description in _MASK_DESCRIPTIONS:
                    display = _mask_id(raw.replace(" ", ""))
                else:
                    display = raw[:50]
                result.violations.append(Violation(
                    rule=self.rule_name,
                    severity=severity,
                    description=description,
                    matched_text=display,
                    position=match.start(),
                ))
        return result
