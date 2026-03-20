"""Abstract base classes for document parsers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Section:
    """A structured section from a parsed document."""
    heading: str | None
    body: str
    level: int = 0
    page_number: int | None = None


@dataclass
class ParseResult:
    """Result of parsing a document."""
    text: str
    metadata: dict = field(default_factory=dict)
    sections: list[Section] = field(default_factory=list)


class BaseParser(ABC):
    """Abstract parser interface. Each file type implements this."""

    @abstractmethod
    def parse(self, file_path: str) -> ParseResult:
        """Parse file and return extracted text + metadata."""
        ...

    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return list of file extensions this parser handles (e.g., ['.pdf'])."""
        ...
