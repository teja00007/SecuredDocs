"""Structured LLM output with Pydantic schema enforcement.

Usage
-----
    from pydantic import BaseModel
    from src.llm.structured import structured_generate

    class Answer(BaseModel):
        answer: str
        confidence: float
        sources: list[str]

    result: Answer = await structured_generate(llm, messages, Answer)
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.core.exceptions import LLMError
from src.core.interfaces import ILLM

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(text: str) -> str:
    """Pull the first JSON block or the entire text if no fence found."""
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    # Try to find raw JSON object/array
    for start_ch, end_ch in (('{', '}'), ('[', ']')):
        start = text.find(start_ch)
        end = text.rfind(end_ch)
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
    return text.strip()


async def structured_generate(
    llm: ILLM,
    messages: list[dict],
    schema: type[T],
    *,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    max_retries: int = 2,
) -> T:
    """Call *llm* and parse the response into a *schema* instance.

    The function injects a system instruction that asks the model to respond
    with valid JSON matching the schema.  On validation failure it retries up
    to *max_retries* times, passing the error back to the model.

    Raises
    ------
    LLMError
        If the model cannot produce a valid response after all retries.
    """
    schema_json = schema.model_json_schema()
    schema_str = json.dumps(schema_json, indent=2)

    system_injection = {
        "role": "system",
        "content": (
            "You MUST respond with a valid JSON object that strictly conforms to the "
            "following JSON Schema. Do NOT include any text outside the JSON object.\n\n"
            f"Schema:\n```json\n{schema_str}\n```"
        ),
    }

    augmented = [system_injection] + list(messages)
    last_error: str = ""

    for attempt in range(max_retries + 1):
        if attempt > 0 and last_error:
            augmented.append({
                "role": "user",
                "content": (
                    f"Your previous response failed validation: {last_error}\n"
                    "Please fix it and return ONLY valid JSON."
                ),
            })

        response = await llm.generate(augmented, temperature=temperature, max_tokens=max_tokens)
        raw = response.content

        try:
            extracted = _extract_json(raw)
            parsed = json.loads(extracted)
            return schema.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)

    raise LLMError(
        f"structured_generate failed after {max_retries + 1} attempts. "
        f"Last error: {last_error}"
    )


async def structured_generate_with_fallback(
    llm: ILLM,
    messages: list[dict],
    schema: type[T],
    fallback: T,
    **kwargs,
) -> T:
    """Like *structured_generate* but returns *fallback* instead of raising."""
    try:
        return await structured_generate(llm, messages, schema, **kwargs)
    except LLMError:
        return fallback
