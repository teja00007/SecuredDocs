"""Agentic Deep Research Service.

Multi-step reasoning: decomposes complex questions into sub-questions,
searches for each independently, then synthesizes a comprehensive answer.
"""

import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from src.core.interfaces import ChunkResult
from src.core.rbac import UserContext, build_visibility_filter

if TYPE_CHECKING:
    from src.services.retrieval_service import RetrievalService
    from src.services.generation_service import GenerationService

logger = logging.getLogger(__name__)

# Maximum characters of context to send to the synthesis LLM
_MAX_CONTEXT_CHARS = 12_000

_DECOMPOSE_SYSTEM = (
    "You are a research planning assistant. "
    "When given a complex question, you break it down into specific, "
    "focused sub-questions that together fully answer the original question."
)

_SYNTHESIS_SYSTEM = (
    "You are a thorough research assistant. "
    "Using ONLY the provided documents, write a comprehensive, well-structured answer. "
    "Organize your answer with clear sections. "
    "Cite the source filenames where appropriate."
)


def _strip_json_fences(raw: str) -> str:
    """Remove markdown code fences from an LLM response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


class DeepResearchService:
    def __init__(
        self,
        retrieval_service: "RetrievalService",
        generation_service: "GenerationService",
    ) -> None:
        self._retrieval = retrieval_service
        self._generation = generation_service

    async def research(
        self,
        query: str,
        user: UserContext,
        collection_id: str | None,
        max_steps: int = 5,
    ) -> AsyncGenerator[dict, None]:
        """Async generator that yields SSE-ready progress events then the final result.

        Yields dicts with keys:
          - type: "step" | "done" | "error"
          - step: name of the current step (for type="step")
          - content: human-readable description of the current step
          - answer / sources / sub_questions / steps_taken (for type="done")
        """
        return self._research_generator(query, user, collection_id, max_steps)

    async def _research_generator(
        self,
        query: str,
        user: UserContext,
        collection_id: str | None,
        max_steps: int,
    ) -> AsyncGenerator[dict, None]:
        steps_taken = 0

        # ── Step 1: Decompose ─────────────────────────────────────────────────
        yield {"type": "step", "step": "decompose", "content": "Breaking down your question..."}

        sub_questions = await self._decompose(query)
        # Respect max_steps limit on sub-question count
        sub_questions = sub_questions[: max(max_steps, 1)]
        steps_taken += 1

        if not sub_questions:
            # Fallback: treat the original query as the only sub-question
            sub_questions = [query]

        logger.debug("Deep research: %d sub-questions for %r", len(sub_questions), query[:80])

        # ── Step 2: Search each sub-question ──────────────────────────────────
        visibility_filter = build_visibility_filter(user)
        all_chunks: list[ChunkResult] = []
        seen_chunk_ids: set[str] = set()

        for sub_q in sub_questions:
            yield {
                "type": "step",
                "step": "searching",
                "content": f"Searching: {sub_q}",
            }
            try:
                chunks = await self._retrieval.retrieve(
                    query_text=sub_q,
                    filter=visibility_filter,
                    collection_id=collection_id,
                    top_k=5,
                )
                for chunk in chunks:
                    if chunk.chunk_id not in seen_chunk_ids:
                        all_chunks.append(chunk)
                        seen_chunk_ids.add(chunk.chunk_id)
            except Exception as exc:
                logger.warning("Deep research retrieval failed for sub-question %r: %s", sub_q, exc)
            steps_taken += 1

        # ── Step 3: Synthesize ────────────────────────────────────────────────
        yield {"type": "step", "step": "synthesizing", "content": "Synthesizing findings..."}
        steps_taken += 1

        answer = await self._synthesize(query, sub_questions, all_chunks)

        # Build de-duplicated source list
        seen_doc_ids: set[str] = set()
        sources: list[dict] = []
        for chunk in all_chunks:
            doc_id = chunk.document_id
            if doc_id not in seen_doc_ids:
                seen_doc_ids.add(doc_id)
                sources.append(
                    {
                        "document_id": doc_id,
                        "filename": chunk.metadata.get("filename", "unknown"),
                        "chunk_text": chunk.text[:300],
                        "score": round(chunk.score, 4),
                    }
                )

        # ── Step 4: Done ──────────────────────────────────────────────────────
        yield {
            "type": "done",
            "answer": answer,
            "sources": sources,
            "sub_questions": sub_questions,
            "steps_taken": steps_taken,
        }

    async def _decompose(self, query: str) -> list[str]:
        """Ask the LLM to break the query into 3-5 sub-questions."""
        prompt = (
            "Break down this research question into 3-5 specific sub-questions that "
            "together would fully answer it. Return ONLY a JSON array of strings.\n\n"
            f"Question: {query}"
        )
        messages = [
            {"role": "system", "content": _DECOMPOSE_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        try:
            import asyncio
            response = await asyncio.wait_for(
                self._generation._llm.generate(messages, temperature=0.2),
                timeout=30.0,
            )
            raw = _strip_json_fences(response.content or "")
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(q) for q in parsed if str(q).strip()]
        except Exception as exc:
            logger.warning("Sub-question decomposition failed: %s", exc)
        return []

    async def _synthesize(
        self,
        original_query: str,
        sub_questions: list[str],
        chunks: list[ChunkResult],
    ) -> str:
        """Synthesize a comprehensive answer from all retrieved chunks."""
        if not chunks:
            # No documents found — answer from general knowledge
            messages = [
                {"role": "system", "content": _SYNTHESIS_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"No documents were found for: '{original_query}'. "
                        "Please provide a helpful general answer based on your knowledge."
                    ),
                },
            ]
        else:
            context_parts: list[str] = []
            total_chars = 0
            for i, chunk in enumerate(chunks, start=1):
                filename = chunk.metadata.get("filename", "unknown")
                page = chunk.metadata.get("page_number", "")
                page_str = f" (page {page})" if page else ""
                entry = f"[{i}] {filename}{page_str}:\n{chunk.text}"
                if total_chars + len(entry) > _MAX_CONTEXT_CHARS:
                    break
                context_parts.append(entry)
                total_chars += len(entry)

            context = "\n\n---\n\n".join(context_parts)
            sub_q_text = "\n".join(f"- {q}" for q in sub_questions)

            user_content = (
                f"Using ONLY the provided documents, write a comprehensive answer to:\n"
                f"'{original_query}'\n\n"
                f"Sub-questions investigated:\n{sub_q_text}\n\n"
                f"Documents:\n{context}\n\n"
                f"Write a well-structured, detailed answer with clear sections."
            )
            messages = [
                {"role": "system", "content": _SYNTHESIS_SYSTEM},
                {"role": "user", "content": user_content},
            ]

        try:
            import asyncio
            response = await asyncio.wait_for(
                self._generation._llm.generate(messages, temperature=0.1),
                timeout=90.0,
            )
            return (response.content or "").strip()
        except Exception as exc:
            logger.error("Deep research synthesis failed: %s", exc, exc_info=True)
            return "Unable to synthesize an answer due to a generation error. Please try again."
