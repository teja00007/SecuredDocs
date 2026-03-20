"""SOX compliance rule — detects financial/audit sensitive content."""

import re

from src.compliance.rules.base import BaseComplianceRule, ScanResult, Violation

_PATTERNS = [
    # Large financial figures
    (re.compile(r"\$\s*\d{1,3}(?:,\d{3}){2,}(?:\.\d{2})?"), "medium", "Large financial figure"),
    # Insider information keywords
    (re.compile(r"\b(?:non-public|MNPI|material\s+non-public|insider\s+(?:info|information|trading))\b", re.IGNORECASE), "critical", "Insider information keyword"),
    # Audit keywords
    (re.compile(r"\b(?:material\s+weakness|significant\s+deficiency|restatement|fraud)\b", re.IGNORECASE), "high", "Audit-sensitive keyword"),
    # Earnings pre-announcement
    (re.compile(r"\b(?:pre-?release|advance\s+notice)\s+(?:of\s+)?(?:earnings|results|guidance)\b", re.IGNORECASE), "critical", "Pre-release earnings information"),
    # Internal control deficiencies
    (re.compile(r"\b(?:internal\s+control\s+(?:failure|deficiency|weakness))\b", re.IGNORECASE), "high", "Internal control deficiency"),
]


class SoxRule(BaseComplianceRule):
    @property
    def rule_name(self) -> str:
        return "SOX"

    def scan(self, text: str) -> ScanResult:
        result = ScanResult(rule_name=self.rule_name)
        for pattern, severity, description in _PATTERNS:
            for match in pattern.finditer(text):
                result.violations.append(Violation(
                    rule=self.rule_name,
                    severity=severity,
                    description=description,
                    matched_text=match.group()[:50],
                    position=match.start(),
                ))
        return result
