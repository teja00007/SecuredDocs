"""Abstract compliance rule base class."""

import re
import signal
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Patterns known to cause catastrophic backtracking
_REDOS_INDICATORS = [
    re.compile(r"\([^)]*\+\)\+"),        # (a+)+
    re.compile(r"\([^)]*\*\)\*"),        # (a*)*
    re.compile(r"\([^)]*\+\)\*"),        # (a+)*
    re.compile(r"\([^)]*\|[^)]*\)\+"),   # (a|b)+  followed by overlap
]

_REDOS_CATASTROPHIC = re.compile(
    r"\((?:[^()]+[+*])+\)[+*]"  # nested quantifiers
)


def _validate_regex(pattern: str) -> re.Pattern:
    """Compile pattern, raising ValueError on invalid regex or suspected ReDoS."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern: {exc}") from exc
    if _REDOS_CATASTROPHIC.search(pattern):
        raise ValueError(
            f"Regex pattern rejected: suspected catastrophic backtracking — {pattern!r}"
        )
    return compiled


@dataclass
class Violation:
    rule: str
    severity: str  # "critical" | "high" | "medium" | "low"
    description: str
    matched_text: str = ""
    position: int | None = None
    confidence: float = 1.0


@dataclass
class ScanResult:
    rule_name: str
    violations: list[Violation] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    @property
    def has_critical(self) -> bool:
        return any(v.severity == "critical" for v in self.violations)


class BaseComplianceRule(ABC):
    """Abstract base for all compliance rules."""

    def __init__(self, pattern: str | None = None) -> None:
        """Optionally accept a custom regex pattern; validate on construction."""
        if pattern is not None:
            self._custom_pattern = _validate_regex(pattern)
        else:
            self._custom_pattern = None

    @property
    @abstractmethod
    def rule_name(self) -> str:
        ...

    @abstractmethod
    def scan(self, text: str) -> ScanResult:
        """Run regex-based scan. Returns ScanResult with any violations found."""
        ...
