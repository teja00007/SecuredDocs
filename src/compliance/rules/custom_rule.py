"""Admin-defined custom compliance rule (regex or keyword)."""

import re
from src.compliance.rules.base import BaseComplianceRule, ScanResult, Violation


class CustomComplianceRule(BaseComplianceRule):
    """A runtime-defined compliance rule backed by a regex or keyword pattern."""

    def __init__(
        self,
        rule_id: str,
        name: str,
        description: str,
        pattern: str,
        pattern_type: str,  # "regex" | "keyword"
        severity: str,      # "critical" | "high" | "medium" | "low"
    ) -> None:
        self._rule_id = rule_id
        self._name = name
        self._description = description
        self._pattern = pattern
        self._pattern_type = pattern_type
        self._severity = severity

        if pattern_type == "regex":
            self._compiled = re.compile(pattern, re.IGNORECASE)
        else:
            self._compiled = None

    @property
    def rule_name(self) -> str:
        return self._rule_id

    @classmethod
    def validate_pattern(cls, pattern: str, pattern_type: str) -> None:
        """Raise ValueError if the pattern is invalid."""
        if pattern_type == "regex":
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex: {e}")
        elif pattern_type != "keyword":
            raise ValueError(f"Unknown pattern_type '{pattern_type}'. Use 'regex' or 'keyword'.")

    def scan(self, text: str) -> ScanResult:
        result = ScanResult(rule_name=self._rule_id)

        if self._pattern_type == "regex" and self._compiled:
            for match in self._compiled.finditer(text):
                result.violations.append(Violation(
                    rule=self._rule_id,
                    severity=self._severity,
                    description=self._description,
                    matched_text=match.group()[:50],
                    position=match.start(),
                ))
        else:
            keyword = self._pattern.lower()
            start = 0
            lower_text = text.lower()
            while True:
                pos = lower_text.find(keyword, start)
                if pos == -1:
                    break
                result.violations.append(Violation(
                    rule=self._rule_id,
                    severity=self._severity,
                    description=self._description,
                    matched_text=text[pos : pos + len(keyword)],
                    position=pos,
                ))
                start = pos + 1

        return result
