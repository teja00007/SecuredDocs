"""DOCX parser using python-docx."""

import unicodedata

from src.core.exceptions import IngestionError
from src.ingestion.parsers.base import BaseParser, ParseResult, Section

_HEADING_STYLES = {
    "heading 1": 1,
    "heading 2": 2,
    "heading 3": 3,
    "heading 4": 4,
    "heading 5": 5,
    "heading 6": 6,
}


class DocxParser(BaseParser):
    def supported_extensions(self) -> list[str]:
        return [".docx"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            from docx import Document as DocxDocument
        except ImportError:
            raise IngestionError("python-docx not installed")

        try:
            doc = DocxDocument(file_path)
        except Exception as e:
            raise IngestionError(f"Failed to open DOCX: {e}")

        paragraphs: list[str] = []
        sections: list[Section] = []
        current_heading: str | None = None
        current_level: int = 0
        body_paragraphs: list[str] = []

        for para in doc.paragraphs:
            text = unicodedata.normalize("NFC", para.text.strip())
            if not text:
                continue

            style_name = (para.style.name or "").lower()
            level = _HEADING_STYLES.get(style_name, 0)

            if level > 0:
                # Save previous section
                if body_paragraphs or current_heading:
                    sections.append(Section(
                        heading=current_heading,
                        body="\n".join(body_paragraphs),
                        level=current_level,
                    ))
                current_heading = text
                current_level = level
                body_paragraphs = []
            else:
                body_paragraphs.append(text)

            paragraphs.append(text)

        # Final section
        if body_paragraphs or current_heading:
            sections.append(Section(
                heading=current_heading,
                body="\n".join(body_paragraphs),
                level=current_level,
            ))

        full_text = "\n\n".join(paragraphs)
        metadata = {
            "file_type": ".docx",
            "paragraph_count": len(paragraphs),
        }

        return ParseResult(text=full_text, metadata=metadata, sections=sections)
