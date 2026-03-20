"""Registry-based parser and chunker factory.

Adding a new format = one parser class + one registration call.
"""

import logging

from src.core.exceptions import UnsupportedFileTypeError
from src.ingestion.parsers.base import BaseParser
from src.ingestion.chunkers.base import BaseChunker

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Registries (populated at import time)
# ──────────────────────────────────────────────

PARSER_REGISTRY: dict[str, type[BaseParser]] = {}
CHUNKER_REGISTRY: dict[str, type[BaseChunker]] = {}  # ext → chunker class
CHUNKER_REGISTRY_BY_NAME: dict[str, type[BaseChunker]] = {}  # strategy name → class


def register_parser(*extensions: str):
    """Decorator: @register_parser('.pdf') on a BaseParser subclass."""
    def decorator(cls: type[BaseParser]) -> type[BaseParser]:
        for ext in extensions:
            PARSER_REGISTRY[ext.lower()] = cls
        return cls
    return decorator


def register_chunker(*extensions: str, strategy_name: str | None = None):
    """Decorator: @register_chunker('.csv', '.xlsx', strategy_name='tabular')."""
    def decorator(cls: type[BaseChunker]) -> type[BaseChunker]:
        for ext in extensions:
            CHUNKER_REGISTRY[ext.lower()] = cls
        if strategy_name:
            CHUNKER_REGISTRY_BY_NAME[strategy_name] = cls
        return cls
    return decorator


# ──────────────────────────────────────────────
# Factory functions
# ──────────────────────────────────────────────

def get_parser(file_type: str) -> BaseParser:
    ext = file_type.lower()
    if ext not in PARSER_REGISTRY:
        raise UnsupportedFileTypeError(f"No parser registered for '{ext}'")
    return PARSER_REGISTRY[ext]()


def get_chunker(file_type: str, override: str | None = None) -> BaseChunker:
    from src.ingestion.chunkers.recursive_chunker import RecursiveChunker
    if override:
        if override not in CHUNKER_REGISTRY_BY_NAME:
            raise UnsupportedFileTypeError(f"No chunker strategy '{override}'")
        return CHUNKER_REGISTRY_BY_NAME[override]()
    ext = file_type.lower()
    cls = CHUNKER_REGISTRY.get(ext, RecursiveChunker)
    return cls()


def list_supported_types() -> list[str]:
    return sorted(PARSER_REGISTRY.keys())


# ──────────────────────────────────────────────
# Self-registration (import to trigger decorators)
# ──────────────────────────────────────────────

def _register_all() -> None:
    from src.ingestion.parsers.pdf_parser import PdfParser
    from src.ingestion.parsers.text_parser import TextParser
    from src.ingestion.parsers.docx_parser import DocxParser
    from src.ingestion.parsers.xlsx_parser import XlsxParser, CsvParser
    from src.ingestion.parsers.html_parser import HtmlParser
    from src.ingestion.parsers.pptx_parser import PptxParser
    from src.ingestion.parsers.json_xml_parser import JsonParser, XmlParser
    from src.ingestion.chunkers.recursive_chunker import RecursiveChunker
    from src.ingestion.chunkers.structural_chunker import StructuralChunker
    from src.ingestion.chunkers.tabular_chunker import TabularChunker
    from src.ingestion.chunkers.hierarchical_chunker import HierarchicalChunker

    # Register parsers
    for ext in [".pdf"]:
        PARSER_REGISTRY[ext] = PdfParser
    for ext in [".txt", ".md", ".markdown"]:
        PARSER_REGISTRY[ext] = TextParser
    for ext in [".docx"]:
        PARSER_REGISTRY[ext] = DocxParser
    for ext in [".xlsx", ".xls"]:
        PARSER_REGISTRY[ext] = XlsxParser
    for ext in [".csv"]:
        PARSER_REGISTRY[ext] = CsvParser
    for ext in [".html", ".htm"]:
        PARSER_REGISTRY[ext] = HtmlParser
    for ext in [".pptx", ".ppt"]:
        PARSER_REGISTRY[ext] = PptxParser
    for ext in [".json"]:
        PARSER_REGISTRY[ext] = JsonParser
    for ext in [".xml"]:
        PARSER_REGISTRY[ext] = XmlParser

    # Register chunkers by extension
    for ext in [".csv", ".xlsx", ".xls"]:
        CHUNKER_REGISTRY[ext] = TabularChunker
    for ext in [".md", ".markdown", ".docx"]:
        CHUNKER_REGISTRY[ext] = StructuralChunker
    for ext in [".pdf", ".txt", ".html", ".htm", ".json", ".xml"]:
        CHUNKER_REGISTRY[ext] = RecursiveChunker
    for ext in [".pptx", ".ppt"]:
        CHUNKER_REGISTRY[ext] = StructuralChunker

    # Register chunkers by strategy name
    CHUNKER_REGISTRY_BY_NAME["recursive"] = RecursiveChunker
    CHUNKER_REGISTRY_BY_NAME["structural"] = StructuralChunker
    CHUNKER_REGISTRY_BY_NAME["tabular"] = TabularChunker
    CHUNKER_REGISTRY_BY_NAME["auto"] = RecursiveChunker
    CHUNKER_REGISTRY_BY_NAME["hierarchical"] = HierarchicalChunker

    # Docling parser — higher quality for PDF/DOCX/PPTX when installed
    try:
        from src.ingestion.parsers.docling_parser import DoclingParser, is_docling_available
        if is_docling_available():
            for ext in [".pdf", ".docx", ".pptx", ".ppt", ".html", ".htm"]:
                PARSER_REGISTRY[ext] = DoclingParser
            logger.info("DoclingParser registered for PDF/DOCX/PPTX/HTML (table-aware)")
    except Exception:
        pass

    # Video processor — requires ffmpeg-python + openai-whisper (or OPENAI_API_KEY)
    try:
        from src.ingestion.processors.video_processor import VideoProcessor
        for ext in [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv"]:
            PARSER_REGISTRY[ext] = VideoProcessor
        logger.info("VideoProcessor registered for video formats (.mp4, .mov, .avi, ...)")
    except Exception as e:
        logger.debug("VideoProcessor not registered: %s", e)

    # Image processor — requires Pillow; optionally openai or open-clip-torch
    try:
        from src.ingestion.processors.image_processor import ImageProcessor
        for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"]:
            PARSER_REGISTRY[ext] = ImageProcessor
        logger.info("ImageProcessor registered for image formats (.jpg, .png, ...)")
    except Exception as e:
        logger.debug("ImageProcessor not registered: %s", e)


_register_all()
