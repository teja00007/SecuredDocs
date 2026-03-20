"""HIPAA compliance rule — detects PHI (Protected Health Information)."""

import re

from src.compliance.rules.base import BaseComplianceRule, ScanResult, Violation


def _mask_ssn(text: str) -> str:
    """Return '***-**-XXXX' keeping only last 4 digits visible."""
    # text is the raw match like '123-45-6789'
    parts = text.split("-")
    if len(parts) == 3:
        return f"***-**-{parts[2]}"
    # 9-digit no-dash form
    if len(text) == 9 and text.isdigit():
        return f"***-**-{text[5:]}"
    return "***-**-****"


_PATTERNS = [
    # SSN with dashes: 123-45-6789
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "critical", "SSN pattern detected"),
    # SSN without dashes in explicit context: 'SSN 123456789' or 'SSN: 123456789'
    (re.compile(r"\bSSN\s*[:=]?\s*(\d{9})\b", re.IGNORECASE), "critical", "SSN pattern detected"),
    # MRN (medical record number) — common formats
    (re.compile(r"\bMRN\s*[::#]?\s*\d{4,10}\b", re.IGNORECASE), "critical", "Medical Record Number (MRN)"),
    # Date of birth
    (re.compile(r"\bDOB\s*[:=]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.IGNORECASE), "high", "Date of Birth"),
    # ICD-10 codes
    (re.compile(r"\b[A-TV-Z][0-9][0-9A-Z]\.[0-9A-Z]{1,4}\b"), "medium", "ICD-10 code"),
    # Patient ID patterns
    (re.compile(r"\bPatient\s+ID\s*[:=#]?\s*[A-Z0-9-]{4,20}\b", re.IGNORECASE), "high", "Patient ID"),
    # Insurance member ID
    (re.compile(r"\bMember\s+ID\s*[:=#]?\s*[A-Z0-9-]{6,20}\b", re.IGNORECASE), "high", "Insurance Member ID"),
    # NPI numbers (National Provider Identifier)
    (re.compile(r"\bNPI\s*[:=#]?\s*\d{10}\b", re.IGNORECASE), "medium", "NPI number"),
]

# Patterns whose matched_text should be masked
_SSN_DESCRIPTIONS = {"SSN pattern detected"}


class HipaaRule(BaseComplianceRule):
    @property
    def rule_name(self) -> str:
        return "HIPAA"

    def scan(self, text: str) -> ScanResult:
        result = ScanResult(rule_name=self.rule_name)
        for pattern, severity, description in _PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group()
                if description in _SSN_DESCRIPTIONS:
                    # For the no-dash SSN pattern the digit group is group(1)
                    digit_part = match.group(1) if match.lastindex else raw
                    masked = _mask_ssn(digit_part if match.lastindex else raw)
                else:
                    masked = raw[:50]
                result.violations.append(Violation(
                    rule=self.rule_name,
                    severity=severity,
                    description=description,
                    matched_text=masked,
                    position=match.start(),
                ))
        return result
