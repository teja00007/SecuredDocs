"""JSON and XML parsers — flattens structured data to readable text."""

import json
import re
from src.core.exceptions import IngestionError
from src.ingestion.parsers.base import BaseParser, ParseResult, Section

try:
    from lxml import etree  # type: ignore
    _LXML_AVAILABLE = True
except ImportError:
    _LXML_AVAILABLE = False
    try:
        import xml.etree.ElementTree as etree_stdlib  # type: ignore
    except ImportError:
        etree_stdlib = None  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# JSON
# ──────────────────────────────────────────────────────────────────────────────

class JsonParser(BaseParser):
    """Parse .json files into human-readable text."""

    def supported_extensions(self) -> list[str]:
        return [".json"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise IngestionError(f"Invalid JSON: {e}")
        except OSError as e:
            raise IngestionError(f"Cannot read JSON file: {e}")

        lines: list[str] = []
        _flatten_json(data, lines, prefix="")
        text = "\n".join(lines)
        return ParseResult(text=text, metadata={"file_type": ".json"}, sections=[])


def _flatten_json(obj, lines: list, prefix: str, depth: int = 0) -> None:
    if depth > 20:
        lines.append(f"{prefix}: [...]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                lines.append(f"{key_path}:")
                _flatten_json(v, lines, key_path, depth + 1)
            else:
                lines.append(f"{key_path}: {v}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            key_path = f"{prefix}[{i}]"
            if isinstance(item, (dict, list)):
                _flatten_json(item, lines, key_path, depth + 1)
            else:
                lines.append(f"{key_path}: {item}")
    else:
        lines.append(f"{prefix}: {obj}")


# ──────────────────────────────────────────────────────────────────────────────
# XML
# ──────────────────────────────────────────────────────────────────────────────

_WHITESPACE_RE = re.compile(r"\s{3,}")


class XmlParser(BaseParser):
    """Parse .xml files into plain text."""

    def supported_extensions(self) -> list[str]:
        return [".xml"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            with open(file_path, "rb") as f:
                raw = f.read()
        except OSError as e:
            raise IngestionError(f"Cannot read XML file: {e}")

        sections: list[Section] = []
        lines: list[str] = []

        if _LXML_AVAILABLE:
            try:
                root = etree.fromstring(raw)
                _extract_xml_lxml(root, lines, sections, depth=0)
            except Exception as e:
                raise IngestionError(f"Failed to parse XML: {e}")
        else:
            try:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(raw.decode("utf-8", errors="replace"))
                _extract_xml_stdlib(root, lines, depth=0)
            except Exception as e:
                raise IngestionError(f"Failed to parse XML: {e}")

        text = _WHITESPACE_RE.sub("\n\n", "\n".join(lines)).strip()
        return ParseResult(text=text, metadata={"file_type": ".xml"}, sections=sections)


def _extract_xml_lxml(element, lines: list, sections: list, depth: int) -> None:
    tag = etree.QName(element.tag).localname if _LXML_AVAILABLE else element.tag
    text = (element.text or "").strip()
    tail = (element.tail or "").strip()

    if depth <= 2 and text:
        sections.append(Section(heading=tag, body=text, level=depth + 1))

    if text:
        lines.append(f"{tag}: {text}")
    for child in element:
        _extract_xml_lxml(child, lines, sections, depth + 1)
    if tail:
        lines.append(tail)


def _extract_xml_stdlib(element, lines: list, depth: int) -> None:
    tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
    text = (element.text or "").strip()
    tail = (element.tail or "").strip()
    if text:
        lines.append(f"{tag}: {text}")
    for child in element:
        _extract_xml_stdlib(child, lines, depth + 1)
    if tail:
        lines.append(tail)
