"""Embedding service with retry logic and Ollama API version detection."""

import asyncio
import logging

from src.core.exceptions import EmbeddingError
from src.core.interfaces import IEmbeddingService

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY = 1.0

# Phrases in the error body that indicate the endpoint itself exists
# but the model is not available — we should NOT fall back to legacy in this case.
_MODEL_NOT_FOUND_PHRASES = ("not found", "try pulling")


class OllamaEmbeddingService(IEmbeddingService):
    """Embedding provider backed by Ollama's embedding API.

    Auto-detects whether the server exposes the current /api/embed endpoint
    (Ollama ≥ 0.1.26) or the legacy /api/embeddings endpoint and caches the
    result for the lifetime of the service instance.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        dimensions: int = 768,
        query_prefix: str = "",
        doc_prefix: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimensions = dimensions
        self._query_prefix = query_prefix
        self._doc_prefix = doc_prefix
        # None = not yet detected, True = use /api/embed, False = use /api/embeddings
        self._use_new_api: bool | None = None
        self._cache = None  # EmbeddingCache | None — set by set_cache()

    def set_cache(self, cache) -> None:
        """Attach an EmbeddingCache instance."""
        self._cache = cache

    async def embed_text(self, text: str) -> list[float]:
        """Embed a query string (applies query_prefix if configured)."""
        if self._cache is not None:
            cached = await self._cache.get(self._query_prefix + text)
            if cached is not None:
                return cached
        result = await self._call_with_retry(self._query_prefix + text)
        if self._cache is not None:
            await self._cache.set(self._query_prefix + text, result)
        return result

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed document chunks (applies doc_prefix if configured)."""
        results: list[list[float]] = []
        for t in texts:
            full_text = self._doc_prefix + t
            if self._cache is not None:
                cached = await self._cache.get(full_text)
                if cached is not None:
                    results.append(cached)
                    continue
            emb = await self._call_with_retry(full_text)
            if self._cache is not None:
                await self._cache.set(full_text, emb)
            results.append(emb)
        return results

    # ── internal helpers ──────────────────────────────────────────────────────

    async def _call_with_retry(self, text: str) -> list[float]:
        import httpx

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    return await self._dispatch(client, text)
            except httpx.ConnectError as e:
                logger.error("Cannot connect to Ollama for embedding: %s", e)
                raise EmbeddingError(f"Cannot connect to Ollama at {self._base_url}: {e}") from e
            except EmbeddingError:
                raise  # propagate model-not-found / permanent errors immediately
            except Exception as e:
                last_error = e
                delay = _BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Embedding attempt %d failed: %s. Retrying in %.1fs",
                    attempt + 1, e, delay,
                )
                await asyncio.sleep(delay)

        raise EmbeddingError(f"Embedding failed after {_MAX_RETRIES} retries: {last_error}")

    async def _dispatch(self, client, text: str) -> list[float]:
        """Call the correct Ollama embedding endpoint, auto-detecting on first use."""
        import httpx

        if self._use_new_api is True:
            return await self._call_new(client, text)
        if self._use_new_api is False:
            return await self._call_legacy(client, text)

        # ── First call: probe which endpoint exists ──
        try:
            result = await self._call_new(client, text)
            self._use_new_api = True
            return result
        except httpx.HTTPStatusError as exc:
            body = exc.response.text.lower()
            if exc.response.status_code == 404 and not any(p in body for p in _MODEL_NOT_FOUND_PHRASES):
                # 404 because the endpoint itself doesn't exist → fall back to legacy
                logger.info("Ollama /api/embed not available, falling back to /api/embeddings")
                result = await self._call_legacy(client, text)
                self._use_new_api = False
                return result
            # 404 because the model is missing, or some other HTTP error
            raise EmbeddingError(
                f"Ollama embedding error (model={self._model}): {exc.response.text}"
            ) from exc

    async def _call_new(self, client, text: str) -> list[float]:
        """POST /api/embed — Ollama ≥ 0.1.26"""
        import httpx

        url = f"{self._base_url}/api/embed"
        response = await client.post(url, json={"model": self._model, "input": text})
        if response.status_code == 404:
            raise httpx.HTTPStatusError("404", request=response.request, response=response)
        response.raise_for_status()
        embeddings = response.json().get("embeddings", [])
        if embeddings:
            return embeddings[0]
        return []

    async def _call_legacy(self, client, text: str) -> list[float]:
        """POST /api/embeddings — legacy Ollama"""
        import httpx

        url = f"{self._base_url}/api/embeddings"
        response = await client.post(url, json={"model": self._model, "prompt": text})
        if response.status_code == 404:
            body = response.text.lower()
            raise EmbeddingError(
                f"Ollama embedding error (model={self._model}): {response.text}"
            )
        response.raise_for_status()
        return response.json().get("embedding", [])
