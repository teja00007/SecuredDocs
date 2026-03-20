"""Cross-encoder re-ranking service — rerank candidates after initial retrieval.

Three implementations:
  - NoOpReRanker    : passthrough, returns candidates unchanged (default when RERANKER_TYPE=none)
  - CohereReRanker  : calls Cohere /v1/rerank API
  - BGEReRanker     : calls a local TEI (Text Embeddings Inference) or llama.cpp rerank endpoint

Factory:
    from src.services.cross_encoder_reranker import get_reranker
    reranker = get_reranker(settings)
    reranked = await reranker.rerank(query, chunks, top_n=5)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from src.core.interfaces import ChunkResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseReRanker(ABC):
    """Interface all re-rankers must satisfy."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        chunks: list[ChunkResult],
        top_n: int = 5,
    ) -> list[ChunkResult]:
        """Return up to top_n chunks ordered by relevance to query."""
        ...


# ---------------------------------------------------------------------------
# No-op passthrough (used when RERANKER_TYPE=none)
# ---------------------------------------------------------------------------

class NoOpReRanker(BaseReRanker):
    """Return the first top_n chunks without any reranking."""

    async def rerank(
        self,
        query: str,
        chunks: list[ChunkResult],
        top_n: int = 5,
    ) -> list[ChunkResult]:
        return chunks[:top_n]


# ---------------------------------------------------------------------------
# Cohere re-ranker
# ---------------------------------------------------------------------------

class CohereReRanker(BaseReRanker):
    """Re-rank using the Cohere /v1/rerank API.

    Docs: https://docs.cohere.com/reference/rerank
    """

    _ENDPOINT = "https://api.cohere.com/v1/rerank"
    _DEFAULT_MODEL = "rerank-english-v3.0"

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        if not api_key:
            raise ValueError("CohereReRanker requires a non-empty COHERE_API_KEY")
        self._api_key = api_key
        self._model = model

    async def rerank(
        self,
        query: str,
        chunks: list[ChunkResult],
        top_n: int = 5,
    ) -> list[ChunkResult]:
        if not chunks:
            return []

        documents = [c.text for c in chunks]

        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(chunks)),
            "return_documents": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self._ENDPOINT, json=payload, headers=headers
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning(
                "Cohere rerank API call failed — falling back to original order: %s", exc
            )
            return chunks[:top_n]

        reranked: list[ChunkResult] = []
        for result in data.get("results", []):
            idx = result["index"]
            relevance_score = result.get("relevance_score", 0.0)
            original = chunks[idx]
            reranked.append(
                ChunkResult(
                    chunk_id=original.chunk_id,
                    document_id=original.document_id,
                    text=original.text,
                    metadata=original.metadata,
                    score=round(relevance_score, 6),
                )
            )

        return reranked


# ---------------------------------------------------------------------------
# BGE (local TEI / llama.cpp) re-ranker
# ---------------------------------------------------------------------------

class BGEReRanker(BaseReRanker):
    """Re-rank using a locally hosted cross-encoder via the TEI /rerank endpoint.

    Compatible with:
      - HuggingFace Text Embeddings Inference (TEI) with a cross-encoder model
      - Any HTTP endpoint accepting { "query": str, "texts": [str] }
        and returning [{ "index": int, "score": float }, ...]
    """

    def __init__(self, base_url: str = "http://localhost:8081") -> None:
        self._endpoint = base_url.rstrip("/") + "/rerank"

    async def rerank(
        self,
        query: str,
        chunks: list[ChunkResult],
        top_n: int = 5,
    ) -> list[ChunkResult]:
        if not chunks:
            return []

        texts = [c.text for c in chunks]
        payload = {"query": query, "texts": texts, "truncate": True}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(self._endpoint, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning(
                "BGE rerank endpoint %s failed — falling back to original order: %s",
                self._endpoint,
                exc,
            )
            return chunks[:top_n]

        # TEI returns a list sorted by score descending
        scored: list[tuple[int, float]] = []
        for item in data:
            idx = item.get("index", 0)
            score = float(item.get("score", 0.0))
            scored.append((idx, score))

        # Sort descending by score (TEI already does this, but be defensive)
        scored.sort(key=lambda x: x[1], reverse=True)

        reranked: list[ChunkResult] = []
        for idx, score in scored[:top_n]:
            original = chunks[idx]
            reranked.append(
                ChunkResult(
                    chunk_id=original.chunk_id,
                    document_id=original.document_id,
                    text=original.text,
                    metadata=original.metadata,
                    score=round(score, 6),
                )
            )

        return reranked


# ---------------------------------------------------------------------------
# Local flashrank re-ranker (CPU, no API key, uses ONNX runtime)
# ---------------------------------------------------------------------------

class LocalFlashReRanker(BaseReRanker):
    """Re-rank using flashrank — a lightweight CPU cross-encoder backed by ONNX.

    Model is downloaded once on first use (~60 MB) and cached locally.
    No GPU, no API key, no separate container required.

    Compatible models (flashrank built-ins):
      ms-marco-MiniLM-L-12-v2  (default, balanced speed/quality)
      ms-marco-MultiBERT-L-12  (multilingual)
      rank-T5-flan              (T5-based, higher quality, slower)
    """

    def __init__(self, model_name: str = "ms-marco-MiniLM-L-12-v2") -> None:
        self._model_name = model_name
        self._ranker = None  # lazy-initialise to avoid slow startup

    def _get_ranker(self):
        if self._ranker is None:
            try:
                from flashrank import Ranker
                self._ranker = Ranker(model_name=self._model_name)
                logger.info("LocalFlashReRanker loaded model: %s", self._model_name)
            except ImportError:
                raise ImportError(
                    "flashrank is not installed. Run: pip install flashrank"
                )
        return self._ranker

    async def rerank(
        self,
        query: str,
        chunks: list[ChunkResult],
        top_n: int = 5,
    ) -> list[ChunkResult]:
        if not chunks:
            return []

        import asyncio
        from flashrank import RerankRequest

        ranker = self._get_ranker()
        passages = [{"id": i, "text": c.text} for i, c in enumerate(chunks)]
        request = RerankRequest(query=query, passages=passages)

        try:
            results = await asyncio.to_thread(ranker.rerank, request)
        except Exception as exc:
            logger.warning(
                "LocalFlashReRanker failed — falling back to original order: %s", exc
            )
            return chunks[:top_n]

        reranked: list[ChunkResult] = []
        for item in results[:top_n]:
            idx = item.get("id", 0)
            score = float(item.get("score", 0.0))
            original = chunks[idx]
            reranked.append(
                ChunkResult(
                    chunk_id=original.chunk_id,
                    document_id=original.document_id,
                    text=original.text,
                    metadata=original.metadata,
                    score=round(score, 6),
                )
            )
        return reranked


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_reranker(settings) -> BaseReRanker:
    """Instantiate the configured re-ranker based on RERANKER_TYPE setting.

    Args:
        settings: application Settings instance.

    Returns:
        A BaseReRanker instance (NoOpReRanker by default).
    """
    reranker_type = getattr(settings, "RERANKER_TYPE", "none").lower()

    if reranker_type == "local":
        model = getattr(settings, "LOCAL_RERANKER_MODEL", "ms-marco-MiniLM-L-12-v2")
        logger.info("Re-ranker: local flashrank (model=%s)", model)
        return LocalFlashReRanker(model_name=model)

    if reranker_type == "cohere":
        api_key = getattr(settings, "COHERE_API_KEY", "")
        logger.info("Re-ranker: Cohere (model=rerank-english-v3.0)")
        return CohereReRanker(api_key=api_key)

    if reranker_type == "bge":
        url = getattr(settings, "RERANKER_URL", "http://localhost:8081")
        logger.info("Re-ranker: BGE local TEI at %s", url)
        return BGEReRanker(base_url=url)

    if reranker_type not in ("none", ""):
        logger.warning(
            "Unknown RERANKER_TYPE=%r — defaulting to NoOpReRanker", reranker_type
        )

    return NoOpReRanker()
