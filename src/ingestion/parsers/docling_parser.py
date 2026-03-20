"""Docling-based document parser for PDF, DOCX, PPTX, HTML.

Docling (IBM, Apache 2.0) preserves table structure as Markdown,
handles multi-column PDFs, and runs fully locally on M1 Metal.

Install: pip install docling

Falls back gracefully to the standard parser if Docling is not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import InputFormat
    _DOCLING_AVAILABLE = True
except ImportError:
    _DOCLING_AVAILABLE = False


class ParseResult:
    """Minimal parse result compatible with existing parsers."""
    def __init__(self, text: str, metadata: dict, sections: list[str]) -> None:
        self.text = text
        self.metadata = metadata
        self.sections = sections


class DoclingParser:
    """Universal parser using IBM Docling.

    Handles PDF, DOCX, PPTX, HTML with table extraction to Markdown.
    Preserves document structure (headings, tables, lists) far better
    than the standard pymupdf/python-docx parsers.
    """

    SUPPORTED = {".pdf", ".docx", ".pptx", ".ppt", ".html", ".htm"}

    def __init__(self) -> None:
        if not _DOCLING_AVAILABLE:
            raise ImportError(
                "docling is not installed. Run: pip install docling\n"
                "Requires: brew install libmagic  (macOS)"
            )
        self._converter = DocumentConverter()

    def parse(self, file_path: str) -> ParseResult:
        """Parse document and return full text with preserved structure."""
        path = Path(file_path)
        try:
            result = self._converter.convert(str(path))
            doc = result.document

            # Export as Markdown — preserves tables, headings, lists
            markdown_text = doc.export_to_markdown()

            # Extract section headings for metadata
            sections: list[str] = []
            for item in doc.texts:
                if hasattr(item, "label") and "heading" in str(item.label).lower():
                    sections.append(item.text)

            metadata: dict = {
                "filename": path.name,
                "file_type": path.suffix.lower(),
                "parser": "docling",
                "page_count": getattr(doc, "num_pages", None),
            }

            logger.info(
                "DoclingParser: parsed %s (%d chars, %d sections)",
                path.name,
                len(markdown_text),
                len(sections),
            )
            return ParseResult(
                text=markdown_text,
                metadata=metadata,
                sections=sections,
            )

        except Exception as exc:
            logger.warning(
                "DoclingParser failed for %s: %s — falling back to text", path.name, exc
            )
            # Last-resort fallback: read raw bytes as text
            try:
                text = path.read_text(errors="replace")
            except Exception:
                text = ""
            return ParseResult(
                text=text,
                metadata={"filename": path.name, "parser": "fallback"},
                sections=[],
            )


def is_docling_available() -> bool:
    return _DOCLING_AVAILABLE
