"""PCI-DSS compliance rule — detects payment card data."""

import re

from src.compliance.rules.base import BaseComplianceRule, ScanResult, Violation


def _luhn_valid(number: str) -> bool:
    """Return True if the digit string passes the Luhn algorithm."""
    digits = [int(d) for d in number]
    digits.reverse()
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _mask_card(raw: str) -> str:
    """Keep only last 4 digits visible: ****-****-****-1111."""
    digits = re.sub(r"[\s\-]", "", raw)
    if len(digits) >= 4:
        return f"****-****-****-{digits[-4:]}"
    return "****"


# Raw card patterns (digits only, no separators) — used for Luhn check
_CARD_RE = re.compile(
    r"(?<!\d)"
    r"(4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})"
    r"(?!\d)"
)

# Card with spaces or dashes as separators
_CARD_SEP_RE = re.compile(
    r"(?<!\d)"
    r"(4[0-9]{3}[\s\-][0-9]{4}[\s\-][0-9]{4}[\s\-][0-9]{4}"   # Visa 16 spaced
    r"|5[1-5][0-9]{2}[\s\-][0-9]{4}[\s\-][0-9]{4}[\s\-][0-9]{4}"  # MC 16 spaced
    r"|3[47][0-9]{2}[\s\-][0-9]{6}[\s\-][0-9]{5}"              # Amex 15 spaced
    r")"
    r"(?!\d)"
)

_OTHER_PATTERNS = [
    # CVV/CVC
    (re.compile(r"\b(?:CVV|CVC|CVV2|CVC2)\s*[:=]?\s*\d{3,4}\b", re.IGNORECASE), "critical", "CVV/CVC code"),
    # Card expiry
    (re.compile(r"\b(?:EXP|expiry|expiration)\s*[:=]?\s*\d{1,2}/\d{2,4}\b", re.IGNORECASE), "high", "Card expiry date"),
    # Bank account numbers — "ACCOUNT NO" or "ACCOUNT #"
    (re.compile(r"\bACCOUNT\s+(?:NO\.?|#)\s*[:=]?\s*\d{8,17}\b", re.IGNORECASE), "high", "Bank account number"),
    # Routing numbers (US ABA)
    (re.compile(r"\b(?:ROUTING|ABA)\s*[:=#]?\s*\d{9}\b", re.IGNORECASE), "high", "Routing number"),
]


class PciDssRule(BaseComplianceRule):
    @property
    def rule_name(self) -> str:
        return "PCI-DSS"

    def scan(self, text: str) -> ScanResult:
        result = ScanResult(rule_name=self.rule_name)

        # Continuous-digit card numbers (Luhn-validated)
        for match in _CARD_RE.finditer(text):
            digits = match.group(1)
            if _luhn_valid(digits):
                result.violations.append(Violation(
                    rule=self.rule_name,
                    severity="critical",
                    description="Credit card number",
                    matched_text=_mask_card(digits),
                    position=match.start(),
                ))

        # Spaced/dashed card numbers (Luhn-validated)
        for match in _CARD_SEP_RE.finditer(text):
            raw = match.group(1)
            digits = re.sub(r"[\s\-]", "", raw)
            if _luhn_valid(digits):
                result.violations.append(Violation(
                    rule=self.rule_name,
                    severity="critical",
                    description="Credit card number",
                    matched_text=_mask_card(raw),
                    position=match.start(),
                ))

        # Other PCI patterns
        for pattern, severity, description in _OTHER_PATTERNS:
            for match in pattern.finditer(text):
                result.violations.append(Violation(
                    rule=self.rule_name,
                    severity=severity,
                    description=description,
                    matched_text=match.group()[:50],
                    position=match.start(),
                ))

        return result
