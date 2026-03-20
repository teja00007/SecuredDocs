"""Query rewriting service — improve the user query before retrieval.

Three strategies:
  - NoOpRewriter      : passthrough, returns the original query unchanged
  - QueryRewriter     : simple single-query rewrite (original implementation)
  - HyDERewriter      : generates a hypothetical answer document then embeds it
  - MultiQueryRewriter: generates N query variants, runs all searches, deduplicates

Factory:
    from src.services.query_rewriter import get_query_rewriter
    rewriter = get_query_rewriter(settings, llm_service)
    result = await rewriter.rewrite(query, chat_history)

For HyDE and MultiQuery the factory returns a wrapper that RAGService/RetrievalService
can call exactly like the original QueryRewriter.  The multi-query deduplication
logic lives in MultiQueryRewriter.retrieve() which wraps a RetrievalService.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from src.core.interfaces import ILLM, ChunkResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared system prompts
# ---------------------------------------------------------------------------

_REWRITE_SYSTEM = (
    "You are a search query optimizer. "
    "Rewrite the user's question as a concise, self-contained search query "
    "that captures the key intent without conversational phrasing. "
    "If context from prior messages is needed, incorporate it. "
    "Reply with ONLY the rewritten query — no explanation, no quotes."
)

_HYDE_SYSTEM = (
    "You are a knowledgeable assistant. "
    "Given a question, write a short (3-5 sentence) hypothetical passage that "
    "would be the ideal answer to the question as if it came from an authoritative document. "
    "Reply with ONLY the passage text — no preamble, no explanation."
)

_MULTI_SYSTEM = (
    "You are a search query optimizer. "
    "Generate {n} different search query phrasings for the same question. "
    "Each phrasing should capture the same intent but use different vocabulary or structure. "
    "Reply with ONLY the queries, one per line — no numbering, no explanations."
)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseQueryRewriter(ABC):
    """Interface all query rewriters must satisfy."""

    @abstractmethod
    async def rewrite(self, query: str, chat_history: list[dict] | None = None) -> str:
        """Return the (possibly rewritten) query string."""
        ...


# ---------------------------------------------------------------------------
# NoOpRewriter — passthrough
# ---------------------------------------------------------------------------

class NoOpRewriter(BaseQueryRewriter):
    async def rewrite(self, query: str, chat_history: list[dict] | None = None) -> str:
        return query


# ---------------------------------------------------------------------------
# QueryRewriter — original single-rewrite implementation
# ---------------------------------------------------------------------------

class QueryRewriter(BaseQueryRewriter):
    """Rewrite the query once for better keyword/semantic overlap."""

    def __init__(self, llm: ILLM) -> None:
        self._llm = llm

    async def rewrite(self, query: str, chat_history: list[dict] | None = None) -> str:
        """Return a rewritten query, or the original if rewriting fails."""
        messages: list[dict] = [{"role": "system", "content": _REWRITE_SYSTEM}]

        # Include last 4 messages (2 turns) for context
        if chat_history:
            messages.extend(chat_history[-4:])

        messages.append({"role": "user", "content": f"Rewrite this search query: {query}"})

        try:
            result = await self._llm.generate(messages=messages, temperature=0.0, max_tokens=128)
            rewritten = result.content.strip()
            if rewritten:
                logger.debug("Query rewritten: %r -> %r", query, rewritten)
                return rewritten
        except Exception as exc:
            logger.warning("Query rewriting failed, using original: %s", exc)

        return query


# ---------------------------------------------------------------------------
# HyDERewriter — Hypothetical Document Embeddings
# ---------------------------------------------------------------------------

class HyDERewriter(BaseQueryRewriter):
    """Generate a hypothetical ideal-answer document; embed that instead of the query.

    The returned string is the hypothetical document text.  The embedding
    service in RetrievalService will embed it as if it were the query.
    """

    def __init__(self, llm: ILLM) -> None:
        self._llm = llm

    async def rewrite(self, query: str, chat_history: list[dict] | None = None) -> str:
        """Return a hypothetical answer document for the query, or the original query on failure."""
        messages: list[dict] = [{"role": "system", "content": _HYDE_SYSTEM}]

        if chat_history:
            messages.extend(chat_history[-4:])

        messages.append({"role": "user", "content": query})

        try:
            result = await self._llm.generate(messages=messages, temperature=0.3, max_tokens=256)
            hypothesis = result.content.strip()
            if hypothesis:
                logger.debug(
                    "HyDE hypothesis generated for query %r (%d chars)", query, len(hypothesis)
                )
                return hypothesis
        except Exception as exc:
            logger.warning("HyDE rewriting failed, using original query: %s", exc)

        return query


# ---------------------------------------------------------------------------
# MultiQueryRewriter — generate N variants, run all searches, deduplicate
# ---------------------------------------------------------------------------

class MultiQueryRewriter(BaseQueryRewriter):
    """Generate N query variants via LLM.

    rewrite() returns the original query so that the standard single-search
    path is unaffected.  The actual multi-search deduplication is performed
    by retrieve_multi() which should be called from RAGService when this
    rewriter is active.
    """

    def __init__(self, llm: ILLM, n: int = 3) -> None:
        self._llm = llm
        self._n = max(1, n)

    async def rewrite(self, query: str, chat_history: list[dict] | None = None) -> str:
        """Return the original query (multi-query expansion happens in retrieve_multi)."""
        return query

    async def generate_variants(
        self, query: str, chat_history: list[dict] | None = None
    ) -> list[str]:
        """Generate up to self._n query variants.  Always includes the original."""
        system_prompt = _MULTI_SYSTEM.format(n=self._n)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if chat_history:
            messages.extend(chat_history[-4:])

        messages.append({"role": "user", "content": query})

        variants: list[str] = [query]  # always include original

        try:
            result = await self._llm.generate(
                messages=messages, temperature=0.6, max_tokens=256
            )
            lines = [l.strip() for l in result.content.splitlines() if l.strip()]
            for line in lines[: self._n]:
                if line and line != query:
                    variants.append(line)
            logger.debug(
                "MultiQuery generated %d variants for %r: %s",
                len(variants) - 1,
                query,
                variants[1:],
            )
        except Exception as exc:
            logger.warning("MultiQuery variant generation failed, using original only: %s", exc)

        return variants

    async def retrieve_multi(
        self,
        query: str,
        retrieval_service,
        filter: dict,
        collection_id: str | None,
        top_k: int,
        chat_history: list[dict] | None = None,
    ) -> list[ChunkResult]:
        """Run retrieval for each query variant, then deduplicate keeping highest score.

        Args:
            query:             Original user query.
            retrieval_service: A RetrievalService instance.
            filter:            RBAC visibility filter dict.
            collection_id:     Optional collection scoping.
            top_k:             Number of results to return after deduplication.
            chat_history:      Optional conversation history for context.

        Returns:
            Deduplicated list of ChunkResult, capped at top_k.
        """
        variants = await self.generate_variants(query, chat_history)

        # Run all searches concurrently
        tasks = [
            retrieval_service.retrieve(
                query_text=variant,
                filter=filter,
                collection_id=collection_id,
                top_k=top_k,
            )
            for variant in variants
        ]
        results_per_variant: list[list[ChunkResult]] = await asyncio.gather(
            *tasks, return_exceptions=False
        )

        # Merge: keep highest score per chunk_id
        best_by_id: dict[str, ChunkResult] = {}
        for results in results_per_variant:
            for chunk in results:
                existing = best_by_id.get(chunk.chunk_id)
                if existing is None or chunk.score > existing.score:
                    best_by_id[chunk.chunk_id] = chunk

        merged = sorted(best_by_id.values(), key=lambda c: c.score, reverse=True)
        return merged[:top_k]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_query_rewriter(settings, llm) -> BaseQueryRewriter:
    """Instantiate the correct query rewriter based on settings.

    Args:
        settings: application Settings instance.
        llm:      An ILLM instance.

    Returns:
        A BaseQueryRewriter instance.
    """
    if not getattr(settings, "QUERY_REWRITING_ENABLED", False):
        return NoOpRewriter()

    mode = getattr(settings, "QUERY_REWRITE_MODE", "multi").lower()

    if mode == "hyde":
        logger.info("Query rewriter: HyDE (hypothetical document embeddings)")
        return HyDERewriter(llm=llm)

    if mode == "multi":
        count = getattr(settings, "QUERY_REWRITE_COUNT", 3)
        logger.info("Query rewriter: MultiQuery (n=%d variants)", count)
        return MultiQueryRewriter(llm=llm, n=count)

    if mode == "single":
        logger.info("Query rewriter: single rewrite")
        return QueryRewriter(llm=llm)

    if mode == "none":
        return NoOpRewriter()

    logger.warning("Unknown QUERY_REWRITE_MODE=%r — defaulting to NoOpRewriter", mode)
    return NoOpRewriter()
