"""Reciprocal Rank Fusion (RRF) reranker for hybrid vector + keyword search.

RRF formula: score(d) = sum(1 / (k + rank_i(d)))  for each ranking i
where k=60 is the standard smoothing constant.

Usage:
    reranker = RRFReranker()
    fused = reranker.fuse(vector_results, bm25_results, top_k=5)
"""

from src.core.interfaces import ChunkResult

_K = 60  # RRF smoothing constant


class RRFReranker:
    """Fuse two ranked lists using Reciprocal Rank Fusion."""

    def fuse(
        self,
        vector_results: list[ChunkResult],
        keyword_results: list[ChunkResult],
        top_k: int = 5,
    ) -> list[ChunkResult]:
        scores: dict[str, float] = {}
        chunks_by_id: dict[str, ChunkResult] = {}

        for rank, chunk in enumerate(vector_results):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (_K + rank + 1)
            chunks_by_id[chunk.chunk_id] = chunk

        for rank, chunk in enumerate(keyword_results):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (_K + rank + 1)
            if chunk.chunk_id not in chunks_by_id:
                chunks_by_id[chunk.chunk_id] = chunk

        ranked = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)[:top_k]

        fused: list[ChunkResult] = []
        for cid in ranked:
            chunk = chunks_by_id[cid]
            fused.append(ChunkResult(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                text=chunk.text,
                metadata=chunk.metadata,
                score=round(scores[cid], 6),
            ))
        return fused
