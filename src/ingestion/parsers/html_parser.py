"""HTML parser — strips tags and extracts text structure."""

import re
from src.core.exceptions import IngestionError
from src.ingestion.parsers.base import BaseParser, ParseResult, Section

try:
    from bs4 import BeautifulSoup  # type: ignore
    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_WHITESPACE_RE = re.compile(r"\s{3,}")


class HtmlParser(BaseParser):
    """Parse .html / .htm files into plain text with section structure."""

    def supported_extensions(self) -> list[str]:
        return [".html", ".htm"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError as e:
            raise IngestionError(f"Failed to read HTML file: {e}")

        if _BS4_AVAILABLE:
            return self._parse_with_bs4(raw)
        return self._parse_fallback(raw)

    def _parse_with_bs4(self, raw: str) -> ParseResult:
        soup = BeautifulSoup(raw, "html.parser")

        # Remove script and style noise
        for tag in soup(["script", "style", "noscript", "meta", "head"]):
            tag.decompose()

        sections: list[Section] = []
        current_heading: str | None = None
        current_level: int = 0
        body_lines: list[str] = []

        for element in soup.body.descendants if soup.body else soup.descendants:  # type: ignore[union-attr]
            tag_name = getattr(element, "name", None)
            if tag_name in _HEADING_TAGS:
                text = element.get_text(separator=" ", strip=True)
                if body_lines or current_heading:
                    sections.append(Section(
                        heading=current_heading,
                        body="\n".join(body_lines).strip(),
                        level=current_level,
                    ))
                    body_lines = []
                current_heading = text
                current_level = _HEADING_TAGS[tag_name]
            elif tag_name in ("p", "li", "td", "th", "div", "span", "article", "section"):
                text = element.get_text(separator=" ", strip=True)
                if text:
                    body_lines.append(text)

        if body_lines or current_heading:
            sections.append(Section(
                heading=current_heading,
                body="\n".join(body_lines).strip(),
                level=current_level,
            ))

        full_text = soup.get_text(separator="\n", strip=True)
        full_text = _WHITESPACE_RE.sub("\n\n", full_text)

        return ParseResult(
            text=full_text,
            metadata={"file_type": ".html"},
            sections=sections,
        )

    def _parse_fallback(self, raw: str) -> ParseResult:
        """Simple regex-based tag stripper when bs4 is unavailable."""
        text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = _WHITESPACE_RE.sub("\n\n", text).strip()
        return ParseResult(text=text, metadata={"file_type": ".html"}, sections=[])
