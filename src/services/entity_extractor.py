"""LLM-based entity and relationship extractor for Knowledge Graph construction.

Extracts named entities and their relationships from document chunk text
using a structured LLM prompt that returns JSON.

Output schema:
    {
        "entities": [{"name": str, "type": str}, ...],
        "relations": [{"source": str, "relation": str, "target": str}, ...]
    }
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.interfaces import ILLM

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = """\
You are an information extraction assistant. Extract named entities and their relationships from text.

Entity types: Person, Organization, Policy, Project, Process, Technology, Location, Date, Role, Product, Event, Concept

For relationships use clear verb phrases: REPORTS_TO, MANAGES, APPLIES_TO, PART_OF, CREATED_BY, RELATED_TO, OWNED_BY, USED_BY, DEFINES, REQUIRES, INCLUDES

Respond ONLY with valid JSON in this exact format — no markdown, no explanation:
{"entities":[{"name":"...","type":"..."}],"relations":[{"source":"...","relation":"...","target":"..."}]}

Rules:
- Extract 3–10 entities max; only specific, meaningful ones
- Entity names must be specific (e.g. "John Smith" not "he"; "Refund Policy v2" not "the policy")
- Only extract relationships that are clearly stated in the text
- If no entities found, return {"entities":[],"relations":[]}\
"""

_QUERY_ENTITIES_SYSTEM = """\
Extract key named entities from the query (people, organizations, policies, projects, products).
Return ONLY a JSON array of strings. Example: ["HR Policy","John Smith","Project Alpha"]
If none, return []\
"""


class EntityExtractor:
    """Extract entities and relationships from text using an LLM."""

    def __init__(self, llm: "ILLM") -> None:
        self._llm = llm

    async def extract(self, text: str) -> dict:
        """Extract entities and relationships from a chunk of text.

        Returns:
            {"entities": [...], "relations": [...]} — always a valid dict, never raises.
        """
        if not text or not text.strip():
            return {"entities": [], "relations": []}

        truncated = text[:1500].strip()
        messages = [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {
                "role": "user",
                "content": f"Extract entities and relationships:\n\n{truncated}",
            },
        ]

        try:
            result = await self._llm.generate(
                messages=messages, temperature=0.0, max_tokens=512
            )
            raw = (result.content or "").strip()
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

            parsed = json.loads(raw)
            entities = [
                e
                for e in parsed.get("entities", [])
                if isinstance(e, dict) and e.get("name") and e.get("type")
            ]
            relations = [
                r
                for r in parsed.get("relations", [])
                if isinstance(r, dict)
                and r.get("source")
                and r.get("target")
                and r.get("relation")
            ]
            return {"entities": entities, "relations": relations}

        except json.JSONDecodeError as exc:
            logger.debug(
                "Entity extraction JSON parse failed (non-fatal): %s", exc
            )
            return {"entities": [], "relations": []}
        except Exception as exc:
            logger.warning("Entity extraction failed (non-fatal): %s", exc)
            return {"entities": [], "relations": []}


async def extract_query_entities(query: str, llm: "ILLM") -> list[str]:
    """Extract named entity strings from a user query for graph lookup.

    Returns a list of entity name strings (empty list on failure).
    """
    if not query.strip():
        return []

    messages = [
        {"role": "system", "content": _QUERY_ENTITIES_SYSTEM},
        {"role": "user", "content": query},
    ]
    try:
        result = await llm.generate(messages=messages, temperature=0.0, max_tokens=128)
        raw = (result.content or "").strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        entities = json.loads(raw)
        if isinstance(entities, list):
            return [str(e).strip() for e in entities if e][:6]
    except Exception as exc:
        logger.debug("Query entity extraction failed (non-fatal): %s", exc)
    return []
