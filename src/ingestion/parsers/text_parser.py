"""Plain text and Markdown parser."""

import re
import unicodedata

from src.core.exceptions import IngestionError
from src.ingestion.parsers.base import BaseParser, ParseResult, Section


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


class TextParser(BaseParser):
    """Parse .txt and .md files, extracting heading structure from Markdown."""

    def supported_extensions(self) -> list[str]:
        return [".txt", ".md", ".markdown"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError as e:
            raise IngestionError(f"Failed to read text file: {e}")

        text = unicodedata.normalize("NFC", raw)
        is_markdown = file_path.lower().endswith((".md", ".markdown"))
        sections: list[Section] = []

        if is_markdown:
            sections = self._extract_markdown_sections(text)

        metadata = {
            "file_type": ".md" if is_markdown else ".txt",
            "is_markdown": is_markdown,
        }

        return ParseResult(text=text, metadata=metadata, sections=sections)

    def _extract_markdown_sections(self, text: str) -> list[Section]:
        sections: list[Section] = []
        lines = text.split("\n")
        current_heading: str | None = None
        current_level: int = 0
        body_lines: list[str] = []

        for line in lines:
            match = _HEADING_RE.match(line)
            if match:
                if body_lines or current_heading:
                    sections.append(Section(
                        heading=current_heading,
                        body="\n".join(body_lines).strip(),
                        level=current_level,
                    ))
                current_heading = match.group(2).strip()
                current_level = len(match.group(1))
                body_lines = []
            else:
                body_lines.append(line)

        # Final section
        if body_lines or current_heading:
            sections.append(Section(
                heading=current_heading,
                body="\n".join(body_lines).strip(),
                level=current_level,
            ))

        return sections
