"""Generation service — build prompt and call LLM."""

import asyncio
import logging
from collections.abc import AsyncIterator

from src.core.interfaces import ILLM, ChunkResult
from src.core.exceptions import LLMError

logger = logging.getLogger(__name__)

_GENERATE_TIMEOUT = 180.0  # seconds before a non-streaming LLM call is abandoned

_SYSTEM_WITH_CONTEXT = """You are Nexus, an enterprise AI assistant. The context documents below were retrieved because they are relevant to the question. Your job is to extract and synthesize the answer from them.

Rules:
- Read ALL context documents carefully before answering.
- Extract specific numbers, percentages, win rates, and metrics EXACTLY as written — copy them verbatim. Do NOT mix up numbers from different entities.
- When a document says "Win rate vs X: N%" that means our win rate AGAINST competitor X is N%. State it clearly as "vs [Competitor]: N%".
- When comparing multiple competitors, address each competitor separately with their own specific facts and win rate.
- Do NOT mention filenames, document names, or source references in your answer.
- If the context documents genuinely contain no information related to the question, say: "The uploaded documents don't contain information about this topic."
- Never fabricate facts or mix up which number belongs to which competitor.
- Be concise and direct — lead with the key facts and numbers, skip preamble.
"""

_SYSTEM_NO_CONTEXT = """You are Nexus, a helpful enterprise AI assistant. Answer the user's question directly using your general knowledge.

- Be concise, friendly, and accurate.
- Do NOT mention documents or knowledge bases.
"""

_LOW_CONFIDENCE_RESPONSE = (
    "I couldn't find sufficient information in the knowledge base to answer this confidently. "
    "The retrieved content had low relevance scores. "
    "Could you rephrase the question or check if the relevant documents have been uploaded?"
)

_LOW_CONFIDENCE_THRESHOLD = 0.0  # disabled — system prompt handles no-answer case


class GenerationService:
    def __init__(self, llm: ILLM) -> None:
        self._llm = llm

    async def generate(
        self,
        query: str,
        context_chunks: list[ChunkResult],
        chat_history: list[dict] | None = None,
        graph_context: str = "",
        low_confidence_threshold: float = _LOW_CONFIDENCE_THRESHOLD,
    ) -> str:
        # Low-confidence fallback: weak retrieval → honest response instead of hallucination
        if context_chunks and low_confidence_threshold > 0:
            top_score = max(c.score for c in context_chunks)
            if top_score < low_confidence_threshold:
                logger.debug(
                    "Low-confidence fallback triggered (top_score=%.4f < threshold=%.4f)",
                    top_score,
                    low_confidence_threshold,
                )
                return _LOW_CONFIDENCE_RESPONSE

        messages = self._build_messages(query, context_chunks, chat_history, graph_context)
        try:
            response = await asyncio.wait_for(
                self._llm.generate(messages, temperature=0.1),
                timeout=_GENERATE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise LLMError(f"LLM request timed out after {_GENERATE_TIMEOUT:.0f} seconds")
        content = (response.content or "").strip()
        if not content:
            raise LLMError("The AI model returned an empty response. Please try again.")
        return content

    async def generate_stream(
        self,
        query: str,
        context_chunks: list[ChunkResult],
        chat_history: list[dict] | None = None,
        graph_context: str = "",
        low_confidence_threshold: float = _LOW_CONFIDENCE_THRESHOLD,
    ) -> AsyncIterator[str]:
        """Yield response tokens one at a time."""
        # Low-confidence fallback: weak retrieval → honest response instead of hallucination
        if context_chunks and low_confidence_threshold > 0:
            top_score = max(c.score for c in context_chunks)
            if top_score < low_confidence_threshold:
                logger.debug(
                    "Low-confidence fallback triggered (top_score=%.4f < threshold=%.4f)",
                    top_score,
                    low_confidence_threshold,
                )
                yield _LOW_CONFIDENCE_RESPONSE
                return

        messages = self._build_messages(query, context_chunks, chat_history, graph_context)
        async for token in self._llm.stream(messages, temperature=0.1):
            yield token

    def _build_messages(
        self,
        query: str,
        context_chunks: list[ChunkResult],
        chat_history: list[dict] | None,
        graph_context: str = "",
    ) -> list[dict]:
        if context_chunks:
            system = _SYSTEM_WITH_CONTEXT
            context_text = self._format_context(context_chunks)
            user_content = f"{context_text}\n\nQuestion: {query}"
            if graph_context:
                user_content = f"{graph_context}\n\n{user_content}"
        else:
            system = _SYSTEM_NO_CONTEXT
            user_content = f"{graph_context}\n\n{query}" if graph_context else query

        messages: list[dict] = [{"role": "system", "content": system}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": user_content})
        return messages

    def _format_context(self, chunks: list[ChunkResult]) -> str:
        # Group multiple chunks from the same document into one entry.
        # This prevents the LLM from treating the same source as separate "documents"
        # and avoids attention scatter across repeated filenames.
        seen_docs: dict[str, list[str]] = {}  # doc_id → list of chunk texts
        doc_order: list[str] = []             # insertion-order doc IDs
        doc_filename: dict[str, str] = {}

        for chunk in chunks:
            doc_id = chunk.document_id
            filename = chunk.metadata.get("filename", "unknown")
            if doc_id not in seen_docs:
                seen_docs[doc_id] = []
                doc_order.append(doc_id)
                doc_filename[doc_id] = filename
            seen_docs[doc_id].append(chunk.text)

        parts: list[str] = []
        for i, doc_id in enumerate(doc_order, start=1):
            filename = doc_filename[doc_id]
            # Deduplicate identical texts (parent_text expansion may produce duplicates
            # when multiple child chunks share the same parent chunk).
            unique_texts: list[str] = []
            seen_text_hashes: set[int] = set()
            for t in seen_docs[doc_id]:
                h = hash(t)
                if h not in seen_text_hashes:
                    seen_text_hashes.add(h)
                    unique_texts.append(t)
            merged_text = "\n\n".join(unique_texts)
            parts.append(f"[{i}] {filename}:\n{merged_text}")

        return "\n\n---\n\n".join(parts)
