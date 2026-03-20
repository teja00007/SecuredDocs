"""PowerPoint (.pptx) parser — extracts slide text with slide structure."""

from src.core.exceptions import IngestionError
from src.ingestion.parsers.base import BaseParser, ParseResult, Section

try:
    from pptx import Presentation  # type: ignore
    from pptx.util import Pt  # type: ignore
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False


class PptxParser(BaseParser):
    """Parse .pptx files into text, one Section per slide."""

    def supported_extensions(self) -> list[str]:
        return [".pptx", ".ppt"]

    def parse(self, file_path: str) -> ParseResult:
        if not _PPTX_AVAILABLE:
            raise IngestionError("python-pptx is not installed. Run: pip install python-pptx")

        try:
            prs = Presentation(file_path)
        except Exception as e:
            raise IngestionError(f"Failed to open PPTX: {e}")

        sections: list[Section] = []
        all_lines: list[str] = []

        for slide_num, slide in enumerate(prs.slides, start=1):
            title_text = ""
            body_lines: list[str] = []

            for shape in slide.shapes:
                if not shape.has_text_frame:
                    continue
                text = shape.text_frame.text.strip()
                if not text:
                    continue
                # Treat the first or title placeholder as heading
                if hasattr(shape, "placeholder_format") and shape.placeholder_format is not None:
                    ph_idx = shape.placeholder_format.idx
                    if ph_idx == 0 and not title_text:  # title placeholder
                        title_text = text
                        continue
                body_lines.append(text)

            heading = title_text or f"Slide {slide_num}"
            body = "\n".join(body_lines)
            sections.append(Section(heading=heading, body=body, level=1))
            all_lines.append(f"## {heading}\n{body}")

        full_text = "\n\n".join(all_lines)
        return ParseResult(
            text=full_text,
            metadata={"file_type": ".pptx", "slide_count": len(prs.slides)},
            sections=sections,
        )
