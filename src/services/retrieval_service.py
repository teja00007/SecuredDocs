"""Retrieval service — embed query and search vector store.

Supports two modes:
  - Vector-only (default): cosine similarity search
  - Hybrid (HYBRID_SEARCH_ENABLED=true): vector + BM25 keyword, fused via RRF
"""

import logging
import re
from collections.abc import Callable

from src.core.interfaces import IEmbeddingService, IVectorStore, ChunkResult
from src.services.reranker import RRFReranker
from src.services.bm25_service import BM25Service


def _metadata_matches(metadata: dict, clause: dict) -> bool:
    """Check whether a BM25 chunk's metadata satisfies a single filter clause."""
    for key, value in clause.items():
        if key in ("$and", "$or"):
            continue
        chunk_value = metadata.get(key, "")
        if key in ("allowed_teams", "allowed_users"):
            if isinstance(value, list):
                # Check if any of the required IDs appear in the pipe-delimited string
                if not any(f"|{v}|" in str(chunk_value) for v in value):
                    return False
            else:
                if str(value) not in str(chunk_value):
                    return False
        elif key == "visibility":
            if chunk_value != value:
                return False
        elif key == "owner_id":
            if chunk_value != value:
                return False
        elif isinstance(value, dict) and "$eq" in value:
            if chunk_value != value["$eq"]:
                return False
        else:
            if chunk_value != value:
                return False
    return True

_FILENAME_RE = re.compile(
    r'^[\w\-. ]+\.(pdf|docx?|xlsx?|pptx?|txt|md|csv|json|xml)$',
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

try:
    from rank_bm25 import BM25Okapi  # type: ignore
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False


class RetrievalService:
    def __init__(
        self,
        embedding_service: IEmbeddingService,
        vector_store: IVectorStore,
        hybrid_enabled: bool = False,
        score_threshold: float = 0.0,
    ) -> None:
        self._embedding = embedding_service
        self._vector_store = vector_store
        self._hybrid_enabled = hybrid_enabled and _BM25_AVAILABLE
        self._score_threshold = score_threshold
        self._reranker = RRFReranker()
        self._bm25_svc = BM25Service()
        if hybrid_enabled and not _BM25_AVAILABLE:
            logger.warning("rank-bm25 not installed — hybrid search disabled. Run: pip install rank-bm25")

    async def retrieve(
        self,
        query_text: str,
        filter: dict,
        collection_id: str | None = None,
        top_k: int = 5,
    ) -> list[ChunkResult]:
        embedding = await self._embedding.embed_text(query_text)
        effective_filter = self._apply_collection_filter(filter, collection_id)

        # Over-fetch for hybrid reranking — BM25 needs more candidates because
        # duplicate uploads and near-duplicate chunks can push the best match
        # past position top_k before deduplication.
        fetch_k = top_k * 4 if self._hybrid_enabled else top_k

        vector_results = await self._vector_store.search(
            embedding=embedding,
            filter=effective_filter,
            top_k=fetch_k,
        )

        # If the query is a bare filename, also fetch chunks from that specific file
        # (semantic similarity of a filename string rarely matches document content)
        stripped = query_text.strip()
        if _FILENAME_RE.match(stripped):
            filename_filter = self._add_filename_filter(effective_filter, stripped)
            filename_results = await self._vector_store.search(
                embedding=embedding,
                filter=filename_filter,
                top_k=top_k,
            )
            vector_results = self._merge_dedupe(filename_results, vector_results, top_k=fetch_k)

        if not self._hybrid_enabled:
            return self._dedupe_by_content(vector_results, top_k)

        # Build a filter function that mirrors the RBAC/visibility rules from the
        # vector store metadata filter so that BM25 results respect the same rules.
        bm25_filter_fn = self._build_bm25_filter(effective_filter)

        # BM25 search — fetch more candidates than vector to compensate for
        # duplicate chunks in the corpus (same doc uploaded multiple times).
        bm25_raw = self._bm25_svc.search(
            query=query_text,
            top_k=fetch_k * 2,
            filter_fn=bm25_filter_fn,
        )

        if not bm25_raw:
            # No BM25 results — fall back to pure vector
            return vector_results[:top_k]

        # Convert BM25 raw dicts to ChunkResult for RRF fusion
        bm25_results: list[ChunkResult] = [
            ChunkResult(
                chunk_id=r["id"],
                document_id=r["metadata"].get("document_id", ""),
                text=r["text"],
                metadata=r["metadata"],
                score=r["score"],
            )
            for r in bm25_raw
        ]

        # Reciprocal Rank Fusion (k=60, standard)
        return self._rrf_fuse(vector_results, bm25_results, top_k=top_k)

    def _rrf_fuse(
        self,
        vector_results: list[ChunkResult],
        bm25_results: list[ChunkResult],
        top_k: int,
        k: int = 60,
    ) -> list[ChunkResult]:
        """Merge two ranked lists using Reciprocal Rank Fusion.

        Score for each document = sum of 1/(rank + k) across lists.
        """
        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, ChunkResult] = {}

        for rank, chunk in enumerate(vector_results):
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + 1.0 / (rank + k)
            chunk_map[chunk.chunk_id] = chunk

        for rank, chunk in enumerate(bm25_results):
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + 1.0 / (rank + k)
            # Prefer the ChunkResult from vector store (has embedding-based score), but
            # register BM25-only chunks so they can appear in the final result set.
            if chunk.chunk_id not in chunk_map:
                chunk_map[chunk.chunk_id] = chunk

        sorted_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)
        fused = [chunk_map[cid] for cid in sorted_ids]
        # Deduplicate: same doc uploaded multiple times → same (filename, chunk_index),
        # different chunk_id. Keep only the highest-ranked copy of each section.
        return self._dedupe_by_content(fused, top_k)

    def _build_bm25_filter(self, effective_filter: dict) -> "Callable[[dict], bool] | None":
        """Return a callable that checks BM25 chunk metadata against the RBAC filter."""
        if not effective_filter:
            return None

        def filter_fn(metadata: dict) -> bool:
            or_clauses = effective_filter.get("$or", [])
            and_clauses = effective_filter.get("$and", [])

            if or_clauses:
                return any(_metadata_matches(metadata, clause) for clause in or_clauses)
            if and_clauses:
                return all(_metadata_matches(metadata, clause) for clause in and_clauses)
            return _metadata_matches(metadata, effective_filter)

        return filter_fn

    def _dedupe_by_content(self, chunks: list[ChunkResult], top_k: int) -> list[ChunkResult]:
        """Remove duplicate chunks from repeated document uploads and apply score threshold.

        Two chunks are duplicates when they share the same (filename, chunk_index).
        Keeps the first (highest-ranked) occurrence.
        Chunks with score below self._score_threshold are discarded.
        """
        seen: set[tuple] = set()
        result: list[ChunkResult] = []
        for chunk in chunks:
            if self._score_threshold > 0.0 and chunk.score < self._score_threshold:
                logger.debug(
                    "Filtered chunk below threshold (score=%.4f < %.4f): %s",
                    chunk.score,
                    self._score_threshold,
                    chunk.metadata.get("filename", chunk.chunk_id),
                )
                continue
            filename = chunk.metadata.get("filename", "")
            chunk_index = chunk.metadata.get("chunk_index", "")
            fingerprint = (filename, str(chunk_index)) if filename else (chunk.chunk_id,)
            if fingerprint not in seen:
                seen.add(fingerprint)
                result.append(chunk)
                if len(result) >= top_k:
                    break
        return result

    def _add_filename_filter(self, existing_filter: dict, filename: str) -> dict:
        """Merge a filename equality clause into an existing RBAC filter."""
        fname_clause = {"filename": filename}
        if not existing_filter:
            return fname_clause
        return {"$and": [existing_filter, fname_clause]}

    def _merge_dedupe(
        self, priority: list[ChunkResult], rest: list[ChunkResult], top_k: int
    ) -> list[ChunkResult]:
        """Put priority results first, then append non-duplicate items from rest."""
        seen = {c.chunk_id for c in priority}
        merged = list(priority)
        for c in rest:
            if c.chunk_id not in seen:
                merged.append(c)
                seen.add(c.chunk_id)
        return merged[:top_k]

    def _apply_collection_filter(self, filter: dict, collection_id: str | None) -> dict:
        if not collection_id:
            return filter
        col_clause = {"collection_id": {"$eq": collection_id}}
        if filter:
            return {"$and": [filter, col_clause]}
        return col_clause

    def _bm25_rerank(
        self, query: str, candidates: list[ChunkResult]
    ) -> list[ChunkResult]:
        tokenized_corpus = [c.text.lower().split() for c in candidates]
        bm25 = BM25Okapi(tokenized_corpus)
        query_tokens = query.lower().split()
        scores = bm25.get_scores(query_tokens)

        ranked = sorted(
            range(len(candidates)),
            key=lambda i: scores[i],
            reverse=True,
        )
        return [candidates[i] for i in ranked]
