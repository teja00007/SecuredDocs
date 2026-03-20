"""RAG orchestration service — the main query pipeline.

Advanced retrieval features (all controlled by config flags):
  - Cross-encoder re-ranking (RERANKER_TYPE != "none")
  - Multi-query expansion (QUERY_REWRITE_MODE="multi")
  - HyDE query rewriting  (QUERY_REWRITE_MODE="hyde")
  - Parent-child chunk expansion (chunks with parent_text in metadata)
"""

import json
import re
import time
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from src.core.interfaces import ChunkResult
from src.core.rbac import UserContext, build_visibility_filter, build_scoped_visibility_filter
from src.repositories.audit_repository import AuditRepository
from src.services.retrieval_service import RetrievalService
from src.services.generation_service import GenerationService

if TYPE_CHECKING:
    from src.services.query_rewriter import BaseQueryRewriter
    from src.services.cross_encoder_reranker import BaseReRanker

logger = logging.getLogger(__name__)


_MAX_CONTEXT_CHUNKS = 6    # max chunks sent to the LLM (internal, for answer quality)
_MAX_CHUNKS_PER_DOC = 6   # allow up to 2 chunks per document
_MAX_SOURCES_DISPLAYED = 3  # max unique documents shown in the UI
_MIN_SOURCE_SCORE = 0.65   # minimum retrieval score to cite a source; top source always shown


def _select_context_chunks(chunks: "list[ChunkResult]") -> "list[ChunkResult]":
    """Return the best deduplicated chunks for the LLM, grouped by document.

    Strategy:
    1. Sort by score descending (reranker score when available, else vector score).
    2. Collect up to _MAX_CHUNKS_PER_DOC chunks per document.
    3. Group all chunks from the same document together, ordered by best score.
       This avoids "lost in the middle" problems — all sections of the top document
       appear consecutively, making it easier for the LLM to extract them.
    4. Cap at _MAX_CONTEXT_CHUNKS total.
    Always returns at least 1 chunk.
    """
    if not chunks:
        return chunks

    sorted_chunks = sorted(chunks, key=lambda c: c.score, reverse=True)

    # Collect up to _MAX_CHUNKS_PER_DOC chunks per doc, preserving score order
    doc_chunks: dict[str, list["ChunkResult"]] = {}
    doc_best_score: dict[str, float] = {}
    for c in sorted_chunks:
        doc_id = c.document_id
        bucket = doc_chunks.setdefault(doc_id, [])
        if len(bucket) < _MAX_CHUNKS_PER_DOC:
            bucket.append(c)
            if doc_id not in doc_best_score:
                doc_best_score[doc_id] = c.score

    # Order document groups by the best-scoring chunk in each group
    ordered_docs = sorted(doc_best_score, key=lambda d: doc_best_score[d], reverse=True)

    result: list["ChunkResult"] = []
    for doc_id in ordered_docs:
        result.extend(doc_chunks[doc_id])
        if len(result) >= _MAX_CONTEXT_CHUNKS:
            break

    return result[:_MAX_CONTEXT_CHUNKS] or sorted_chunks[:1]


def _compute_confidence(chunks: "list[ChunkResult]") -> tuple[float, str]:
    """Derive a confidence score and label from retrieval scores.

    Thresholds are calibrated for cosine-similarity embeddings (nomic-embed-text):
      Verified  ≥ 0.80 — top chunk is clearly on-topic
      Likely    ≥ 0.65 — moderate semantic overlap
      Uncertain  < 0.65 — weak match; answer may be hallucinated or off-topic
    """
    if not chunks:
        return 0.0, "Uncertain"
    # Use the top chunk's score, not the average — the top result is what matters most
    top_score = max(c.score for c in chunks)
    avg = sum(c.score for c in chunks) / len(chunks)
    # Blend: weight top score 70%, average 30% to reward a strong lead result
    blended = round(min(max(top_score * 0.7 + avg * 0.3, 0.0), 1.0), 4)
    if blended >= 0.80:
        return blended, "Verified"
    if blended >= 0.65:
        return blended, "Likely"
    return blended, "Uncertain"

# Queries that are purely conversational and shouldn't search docs
_SKIP_KEYWORDS = re.compile(
    r"^(hi|hello|hey|thanks|thank you|bye|good morning|good afternoon|"
    r"what time is it|what['']?s the (date|time)|tell me a joke|"
    r"how are you|what are you|who are you|what can you do)\W*$",
    re.IGNORECASE,
)


def _should_skip_retrieval(query: str) -> bool:
    """Return True ONLY for pure greetings/small-talk — always search docs otherwise."""
    return bool(_SKIP_KEYWORDS.match(query.strip()))


def _expand_parent_chunks(chunks: "list[ChunkResult]") -> "list[ChunkResult]":
    """Replace child chunk text with parent text when parent_text is stored in metadata.

    For hierarchical (parent-child) chunks the child text is narrow and was
    used only for precision embedding.  The LLM should receive the richer
    parent context instead.
    """
    expanded: list[ChunkResult] = []
    for chunk in chunks:
        parent_text = chunk.metadata.get("parent_text")
        if parent_text and isinstance(parent_text, str) and parent_text.strip():
            expanded.append(
                ChunkResult(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    text=parent_text,
                    metadata=chunk.metadata,
                    score=chunk.score,
                )
            )
        else:
            expanded.append(chunk)
    return expanded


class RAGService:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        generation_service: GenerationService,
        audit_repo: AuditRepository,
        query_rewriter: "BaseQueryRewriter | None" = None,
        reranker: "BaseReRanker | None" = None,
        reranker_top_n: int = 5,
        retrieval_top_k: int = 20,
        kg_service=None,  # KnowledgeGraphService | None
        llm=None,         # ILLM | None — needed for query entity extraction
        semantic_cache=None,  # SemanticCache | None
        low_confidence_threshold: float = 0.20,
    ) -> None:
        self._retrieval = retrieval_service
        self._generation = generation_service
        self._audit_repo = audit_repo
        self._rewriter = query_rewriter
        self._reranker = reranker
        self._reranker_top_n = reranker_top_n
        self._retrieval_top_k = retrieval_top_k
        self._kg_service = kg_service
        self._llm = llm
        self._semantic_cache = semantic_cache
        self._low_confidence_threshold = low_confidence_threshold

    async def _get_graph_context(self, query_text: str) -> str:
        """Query the knowledge graph for entity relationships relevant to the query.

        Returns a formatted string of relationship triples, or "" when KG is
        unavailable or no matching entities are found.  Never raises.
        """
        if self._kg_service is None or self._llm is None:
            return ""
        try:
            from src.services.entity_extractor import extract_query_entities
            entities = await extract_query_entities(query_text, self._llm)
            if not entities:
                return ""
            return await self._kg_service.get_context_for_query(entities)
        except Exception as exc:
            logger.debug("Knowledge graph context retrieval failed (non-fatal): %s", exc)
            return ""

    async def _generate_follow_up_questions(
        self, query: str, answer: str, chunks: "list[ChunkResult]"
    ) -> list[str]:
        """Generate 3 follow-up question suggestions via a second LLM call.

        Returns an empty list on any failure — never raises.
        """
        if not chunks:
            return []
        prompt = (
            f"Based on this answer about '{query}', suggest 3 short follow-up questions "
            "the user might want to ask next. "
            "Return ONLY a JSON array of 3 strings, nothing else."
        )
        messages = [
            {"role": "system", "content": "You are a helpful assistant that suggests concise follow-up questions."},
            {"role": "user", "content": f"Answer: {answer}\n\n{prompt}"},
        ]
        try:
            import asyncio
            response = await asyncio.wait_for(
                self._generation._llm.generate(messages, temperature=0.3),
                timeout=30.0,
            )
            raw = (response.content or "").strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            questions = json.loads(raw)
            if isinstance(questions, list):
                return [str(q) for q in questions[:3]]
            return []
        except Exception as exc:
            logger.debug("Follow-up question generation failed (non-fatal): %s", exc)
            return []

    async def _retrieve_chunks(
        self,
        query_text: str,
        visibility_filter: dict,
        collection_id: str | None,
        top_k: int,
        chat_history: list[dict] | None,
    ) -> "list[ChunkResult]":
        """Run the full retrieval pipeline: rewrite → retrieve → re-rank → expand parents."""
        from src.services.query_rewriter import MultiQueryRewriter, NoOpRewriter

        # --- Step 1: query rewriting ---
        retrieval_query = query_text

        # Multi-query: run separate searches per variant then merge
        if isinstance(self._rewriter, MultiQueryRewriter):
            candidates = await self._rewriter.retrieve_multi(
                query=query_text,
                retrieval_service=self._retrieval,
                filter=visibility_filter,
                collection_id=collection_id,
                top_k=self._retrieval_top_k,
                chat_history=chat_history,
            )
        else:
            # HyDE / single rewrite / no-op — single search path
            if self._rewriter and not isinstance(self._rewriter, NoOpRewriter):
                retrieval_query = await self._rewriter.rewrite(query_text, chat_history)
            candidates = await self._retrieval.retrieve(
                query_text=retrieval_query,
                filter=visibility_filter,
                collection_id=collection_id,
                top_k=self._retrieval_top_k,
            )

        # --- Step 2: cross-encoder re-ranking ---
        # Preserve the retrieval score (cosine similarity or BM25 raw) before
        # the reranker overwrites chunk.score with its own scale.  The
        # retrieval score is used for the UI "matching %" display; the
        # reranker score is used only for ordering.
        for c in candidates:
            c.metadata.setdefault("_retrieval_score", c.score)

        if self._reranker is not None:
            from src.services.cross_encoder_reranker import NoOpReRanker
            if not isinstance(self._reranker, NoOpReRanker):
                candidates = await self._reranker.rerank(
                    query=query_text,
                    chunks=candidates,
                    top_n=self._reranker_top_n,
                )
            else:
                candidates = candidates[: self._reranker_top_n]
        else:
            # No reranker configured — cap at reranker_top_n to honour callers' top_k intent
            candidates = candidates[: top_k]

        # --- Step 3: parent-child text expansion ---
        candidates = _expand_parent_chunks(candidates)

        return candidates

    async def query(
        self,
        query_text: str,
        user: UserContext,
        collection_id: str | None = None,
        top_k: int = 5,
        chat_history: list[dict] | None = None,
    ) -> dict:
        start_ms = time.time() * 1000

        # 1. Build RBAC filter
        visibility_filter = build_visibility_filter(user)

        # Check semantic cache — skip retrieval and generation if hit
        if self._semantic_cache is not None:
            try:
                cached = await self._semantic_cache.get(query_text)
                if cached is not None:
                    return cached
            except Exception as _cache_exc:
                logger.debug("Semantic cache lookup failed (non-fatal): %s", _cache_exc)

        # 2. Retrieve relevant chunks (skip for purely conversational queries)
        retrieval_start_ms = time.time() * 1000
        if _should_skip_retrieval(query_text):
            chunks: list[ChunkResult] = []
        else:
            chunks = await self._retrieve_chunks(
                query_text=query_text,
                visibility_filter=visibility_filter,
                collection_id=collection_id,
                top_k=top_k,
                chat_history=chat_history,
            )
        latency_retrieval_ms = time.time() * 1000 - retrieval_start_ms

        # 3. Graph-augmented context
        graph_context = await self._get_graph_context(query_text)

        # 4. Generate answer — LLM reads only the focused context chunks
        context_chunks = _select_context_chunks(chunks)
        generation_start_ms = time.time() * 1000
        answer = await self._generation.generate(
            query=query_text,
            context_chunks=context_chunks,
            chat_history=chat_history,
            graph_context=graph_context,
        )
        latency_generation_ms = time.time() * 1000 - generation_start_ms

        # 5. Build sources — one entry per document (deduped), highest score wins.
        # Display the retrieval score (cosine similarity, 0-1) rather than the
        # reranker score so the "matching %" always reflects semantic similarity.
        # BM25-only chunks store a raw score > 1; cap those at 1.0.
        seen_doc_ids: dict[str, dict] = {}
        for c in context_chunks:
            doc_id = c.document_id
            score = round(min(c.metadata.get("_retrieval_score", c.score), 1.0), 4)
            if doc_id not in seen_doc_ids or score > seen_doc_ids[doc_id]["score"]:
                seen_doc_ids[doc_id] = {
                    "document_id": doc_id,
                    "filename": c.metadata.get("filename", "unknown"),
                    "chunk_text": c.text,
                    "page_number": c.metadata.get("page_number"),
                    "score": score,
                }
        all_sources = sorted(seen_doc_ids.values(), key=lambda s: s["score"], reverse=True)
        filtered = [s for s in all_sources if s["score"] >= _MIN_SOURCE_SCORE]
        sources = (filtered or all_sources[:1])[:_MAX_SOURCES_DISPLAYED]
        confidence_score, confidence_label = _compute_confidence(context_chunks)

        # 6. Generate follow-up questions (second LLM call, non-blocking on failure)
        follow_up_questions = await self._generate_follow_up_questions(
            query=query_text, answer=answer, chunks=context_chunks
        )

        # 7. Compute eval metrics
        avg_retrieval_score: float | None = None
        if chunks:
            avg_retrieval_score = round(sum(c.score for c in chunks) / len(chunks), 4)
        answer_has_sources = len(chunks) > 0

        # 8. Audit log
        latency_ms = int(time.time() * 1000 - start_ms)
        try:
            await self._audit_repo.log_query(
                user_id=user.user_id,
                query_text=query_text,
                chunks_retrieved=len(chunks),
                response_length=len(answer),
                latency_ms=latency_ms,
                retrieval_score=avg_retrieval_score,
                chunk_count_retrieved=len(chunks),
                answer_has_sources=answer_has_sources,
                answer_length=len(answer),
                latency_retrieval_ms=round(latency_retrieval_ms, 2),
                latency_generation_ms=round(latency_generation_ms, 2),
                collection_id=collection_id,
            )
        except Exception as e:
            logger.warning("Failed to log query audit: %s", e)

        result = {
            "answer": answer,
            "sources": sources,
            "confidence_score": confidence_score,
            "confidence_label": confidence_label,
            "follow_up_questions": follow_up_questions,
        }
        if self._semantic_cache is not None:
            try:
                await self._semantic_cache.set(query_text, result)
            except Exception as _cache_exc:
                logger.debug("Semantic cache store failed (non-fatal): %s", _cache_exc)
        return result

    async def query_stream(
        self,
        query_text: str,
        user: UserContext,
        collection_id: str | None = None,
        top_k: int = 5,
        chat_history: list[dict] | None = None,
        scope: str = "all",
    ) -> AsyncIterator[str | dict]:
        """Yields str tokens then a final dict: {"type": "done", "sources": [...]}."""
        start_ms = time.time() * 1000

        visibility_filter = build_scoped_visibility_filter(user, scope)

        retrieval_start_ms = time.time() * 1000
        if _should_skip_retrieval(query_text):
            chunks: list[ChunkResult] = []
        else:
            chunks = await self._retrieve_chunks(
                query_text=query_text,
                visibility_filter=visibility_filter,
                collection_id=collection_id,
                top_k=top_k,
                chat_history=chat_history,
            )
        latency_retrieval_ms = time.time() * 1000 - retrieval_start_ms

        graph_context = await self._get_graph_context(query_text)

        context_chunks = _select_context_chunks(chunks)
        generation_start_ms = time.time() * 1000
        full_answer_parts: list[str] = []
        async for token in self._generation.generate_stream(
            query=query_text,
            context_chunks=context_chunks,
            chat_history=chat_history,
            graph_context=graph_context,
        ):
            full_answer_parts.append(token)
            yield token
        latency_generation_ms = time.time() * 1000 - generation_start_ms

        full_answer = "".join(full_answer_parts)

        # Deduplicate by document, filter low-relevance sources, cap at _MAX_SOURCES_DISPLAYED
        seen_doc_ids: dict[str, dict] = {}
        for c in context_chunks:
            doc_id = c.document_id
            score = round(min(c.metadata.get("_retrieval_score", c.score), 1.0), 4)
            if doc_id not in seen_doc_ids or score > seen_doc_ids[doc_id]["score"]:
                seen_doc_ids[doc_id] = {
                    "document_id": doc_id,
                    "filename": c.metadata.get("filename", "unknown"),
                    "chunk_text": c.text,
                    "page_number": c.metadata.get("page_number"),
                    "score": score,
                }
        all_sources = sorted(seen_doc_ids.values(), key=lambda s: s["score"], reverse=True)
        filtered = [s for s in all_sources if s["score"] >= _MIN_SOURCE_SCORE]
        sources = (filtered or all_sources[:1])[:_MAX_SOURCES_DISPLAYED]
        confidence_score, confidence_label = _compute_confidence(context_chunks)

        # Generate follow-up questions after the streaming answer is complete
        follow_up_questions = await self._generate_follow_up_questions(
            query=query_text, answer=full_answer, chunks=context_chunks
        )

        yield {
            "type": "done",
            "sources": sources,
            "confidence_score": confidence_score,
            "confidence_label": confidence_label,
            "follow_up_questions": follow_up_questions,
        }

        # Compute eval metrics
        avg_retrieval_score: float | None = None
        if chunks:
            avg_retrieval_score = round(sum(c.score for c in chunks) / len(chunks), 4)
        answer_has_sources = len(chunks) > 0

        latency_ms = int(time.time() * 1000 - start_ms)
        try:
            await self._audit_repo.log_query(
                user_id=user.user_id,
                query_text=query_text,
                chunks_retrieved=len(chunks),
                response_length=len(full_answer),
                latency_ms=latency_ms,
                retrieval_score=avg_retrieval_score,
                chunk_count_retrieved=len(chunks),
                answer_has_sources=answer_has_sources,
                answer_length=len(full_answer),
                latency_retrieval_ms=round(latency_retrieval_ms, 2),
                latency_generation_ms=round(latency_generation_ms, 2),
                collection_id=collection_id,
            )
        except Exception as e:
            logger.warning("Failed to log query audit: %s", e)
