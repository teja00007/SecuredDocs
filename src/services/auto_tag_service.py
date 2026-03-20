"""Auto-tagging service: uses the LLM to suggest descriptive tags for a document.

Opt-in via config: set AUTO_TAGGING_ENABLED=true in environment or .env.
This service is intentionally defensive — any failure is logged and silently
swallowed so that the ingestion pipeline is never blocked by tagging errors.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# Tags must be lowercase, alphanumeric + hyphens, max 32 chars each.
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,31}$")

_PROMPT_TEMPLATE = (
    "Suggest 3-7 short descriptive tags for this document titled '{filename}'. "
    "Tags should describe: topic, document type, subject area. "
    "Return ONLY a JSON array of lowercase single-word or hyphenated tags. "
    "Example: [\"contract\", \"legal\", \"employment\", \"2025\"]\n\n"
    "Document excerpt:\n{text_sample}"
)


class AutoTagService:
    async def generate_tags(
        self,
        document_id: str,
        filename: str,
        text_sample: str,
        llm,
    ) -> list[str]:
        """Ask the LLM to suggest tags for *document_id*.

        Args:
            document_id: UUID of the document (used for logging only).
            filename: Human-readable filename shown in the prompt.
            text_sample: First 2000 chars of extracted document text.
            llm: Any object with an async `generate(messages, temperature)` method
                 that returns an object with a `.content` attribute (matches the
                 existing ILLMService interface used throughout the project).

        Returns:
            A list of 0-7 validated, lowercase, alphanumeric-plus-hyphen tags.
            Returns an empty list on any error.
        """
        if not text_sample or not text_sample.strip():
            logger.debug("AutoTagService: no text sample for document %s — skipping", document_id)
            return []

        sample = text_sample[:2000]
        prompt = _PROMPT_TEMPLATE.format(
            filename=filename,
            text_sample=sample,
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a document classification assistant. "
                    "You output only valid JSON arrays of lowercase tag strings."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            import asyncio
            response = await asyncio.wait_for(
                llm.generate(messages, temperature=0.1),
                timeout=30.0,
            )
            raw = (response.content or "").strip()
        except asyncio.TimeoutError:
            logger.warning(
                "AutoTagService: LLM timed out for document %s — no tags generated", document_id
            )
            return []
        except Exception as exc:
            logger.warning(
                "AutoTagService: LLM call failed for document %s — %s", document_id, exc
            )
            return []

        # Strip markdown fences if the model wrapped its output
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "AutoTagService: LLM returned non-JSON for document %s — %r", document_id, raw[:200]
            )
            return []

        if not isinstance(parsed, list):
            logger.warning(
                "AutoTagService: LLM returned unexpected structure for document %s", document_id
            )
            return []

        # Validate and normalise each tag
        validated: list[str] = []
        for item in parsed:
            tag = str(item).strip().lower()
            # Replace spaces with hyphens so "annual report" → "annual-report"
            tag = re.sub(r"\s+", "-", tag)
            if _TAG_RE.match(tag):
                validated.append(tag)
            else:
                logger.debug("AutoTagService: discarding invalid tag %r for document %s", tag, document_id)

            if len(validated) >= 7:
                break

        return validated
