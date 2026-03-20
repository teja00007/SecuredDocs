"""
TDD Test Cases — Parser Factory (src/ingestion/parser_factory.py)
"""
import pytest

from src.core.exceptions import UnsupportedFileTypeError
from src.ingestion.parser_factory import get_parser, get_chunker
from src.ingestion.parsers.pdf_parser import PdfParser
from src.ingestion.parsers.text_parser import TextParser
from src.ingestion.parsers.docx_parser import DocxParser
from src.ingestion.parsers.xlsx_parser import XlsxParser, CsvParser
from src.ingestion.parsers.html_parser import HtmlParser
from src.ingestion.chunkers.recursive_chunker import RecursiveChunker
from src.ingestion.chunkers.structural_chunker import StructuralChunker
from src.ingestion.chunkers.tabular_chunker import TabularChunker


class TestParserFactory:
    """get_parser() and get_chunker() factory functions."""

    def test_get_parser_pdf(self):
        """get_parser('.pdf') should return PdfParser instance."""
        parser = get_parser(".pdf")
        assert isinstance(parser, PdfParser)

    def test_get_parser_txt(self):
        """get_parser('.txt') should return TextParser instance."""
        parser = get_parser(".txt")
        assert isinstance(parser, TextParser)

    def test_get_parser_md(self):
        """get_parser('.md') should return TextParser instance."""
        parser = get_parser(".md")
        assert isinstance(parser, TextParser)

    def test_get_parser_docx(self):
        """get_parser('.docx') should return DocxParser instance."""
        parser = get_parser(".docx")
        assert isinstance(parser, DocxParser)

    def test_get_parser_csv(self):
        """get_parser('.csv') should return CsvParser instance."""
        parser = get_parser(".csv")
        assert isinstance(parser, CsvParser)

    def test_get_parser_xlsx(self):
        """get_parser('.xlsx') should return XlsxParser instance."""
        parser = get_parser(".xlsx")
        assert isinstance(parser, XlsxParser)

    def test_get_parser_html(self):
        """get_parser('.html') should return HtmlParser instance."""
        parser = get_parser(".html")
        assert isinstance(parser, HtmlParser)

    def test_get_parser_unsupported_raises(self):
        """get_parser('.exe') should raise UnsupportedFileTypeError."""
        with pytest.raises(UnsupportedFileTypeError):
            get_parser(".exe")

    def test_get_parser_case_insensitive(self):
        """get_parser('.PDF') should work same as '.pdf'."""
        parser = get_parser(".PDF")
        assert isinstance(parser, PdfParser)

    def test_get_chunker_pdf(self):
        """get_chunker('.pdf') should return RecursiveChunker for PDFs."""
        chunker = get_chunker(".pdf")
        assert isinstance(chunker, RecursiveChunker)

    def test_get_chunker_csv(self):
        """get_chunker('.csv') should return TabularChunker."""
        chunker = get_chunker(".csv")
        assert isinstance(chunker, TabularChunker)

    def test_get_chunker_txt(self):
        """get_chunker('.txt') should return RecursiveChunker."""
        chunker = get_chunker(".txt")
        assert isinstance(chunker, RecursiveChunker)

    def test_get_chunker_md(self):
        """get_chunker('.md') should return StructuralChunker."""
        chunker = get_chunker(".md")
        assert isinstance(chunker, StructuralChunker)
