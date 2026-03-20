"""PDF parser using pymupdf with OCR fallback for scanned PDFs."""

import logging
import unicodedata

from src.core.exceptions import IngestionError
from src.ingestion.parsers.base import BaseParser, ParseResult, Section

logger = logging.getLogger(__name__)

# Minimum total character count across all pages before OCR is triggered
_OCR_THRESHOLD = 50


class PdfParser(BaseParser):
    """Parse PDF files page-by-page using pymupdf, with Tesseract OCR fallback."""

    def supported_extensions(self) -> list[str]:
        return [".pdf"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            import fitz  # pymupdf
        except ImportError:
            raise IngestionError("pymupdf not installed. Run: pip install pymupdf")

        try:
            doc = fitz.open(file_path)
        except Exception as e:
            raise IngestionError(f"Failed to open PDF: {e}")

        pages_text: list[str] = []
        sections: list[Section] = []

        try:
            for page_num, page in enumerate(doc, start=1):
                text = page.get_text("text")
                if not text.strip():
                    # Scanned page — flag but don't fail (may be recovered by OCR below)
                    text = f"[Page {page_num}: image-only, no text extracted]"
                text = unicodedata.normalize("NFC", text)
                pages_text.append(text)
                sections.append(Section(
                    heading=None,
                    body=text,
                    level=0,
                    page_number=page_num,
                ))
        finally:
            doc.close()

        full_text = "\n\n".join(pages_text)
        ocr_used = False

        # OCR fallback: if extracted text is below threshold, use Tesseract
        # Count non-placeholder text only
        total_meaningful = len("".join(
            t for t in pages_text
            if not (t.startswith("[Page") and "image-only" in t)
        ).strip())

        if total_meaningful < _OCR_THRESHOLD:
            logger.info(
                "PDF '%s' has only %d chars of text — attempting OCR fallback.",
                file_path,
                total_meaningful,
            )
            ocr_result = self._ocr_fallback(file_path, len(pages_text))
            if ocr_result is not None:
                pages_text, sections = ocr_result
                full_text = "\n\n".join(pages_text)
                ocr_used = True

        metadata: dict = {
            "page_count": len(pages_text),
            "file_type": ".pdf",
            "ocr_used": ocr_used,
        }

        return ParseResult(text=full_text, metadata=metadata, sections=sections)

    def _ocr_fallback(
        self, file_path: str, expected_pages: int
    ) -> "tuple[list[str], list[Section]] | None":
        """Convert PDF pages to images and run Tesseract OCR on each page.

        Returns (pages_text, sections) on success, None if OCR is not available.
        """
        try:
            from pdf2image import convert_from_path  # type: ignore
        except ImportError:
            logger.warning(
                "pdf2image not installed — OCR fallback unavailable. "
                "Run: pip install pdf2image"
            )
            return None

        try:
            import pytesseract  # type: ignore
        except ImportError:
            logger.warning(
                "pytesseract not installed — OCR fallback unavailable. "
                "Run: pip install pytesseract"
            )
            return None

        try:
            images = convert_from_path(file_path)
        except Exception as exc:
            logger.warning("pdf2image conversion failed for '%s': %s", file_path, exc)
            return None

        pages_text: list[str] = []
        sections: list[Section] = []

        for page_num, image in enumerate(images, start=1):
            try:
                text = pytesseract.image_to_string(image)
            except Exception as exc:
                logger.warning("Tesseract OCR failed on page %d: %s", page_num, exc)
                text = f"[Page {page_num}: OCR failed]"

            text = unicodedata.normalize("NFC", text)
            pages_text.append(text)
            sections.append(Section(
                heading=None,
                body=text,
                level=0,
                page_number=page_num,
            ))

        logger.info("OCR completed for '%s': %d pages processed.", file_path, len(pages_text))
        return pages_text, sections
