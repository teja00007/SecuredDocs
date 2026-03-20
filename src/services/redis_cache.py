"""Redis-backed semantic cache and embedding cache for RAG queries.

SemanticCache: two-level cache for query → response
  Level 1: exact SHA-256 hash (instant hit for identical queries)
  Level 2: cosine embedding similarity (hit if similarity >= threshold)

EmbeddingCache: Redis hash keyed on (model, text_hash) → embedding vector
  Eliminates 50-120ms Ollama embed calls for repeated texts.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class SemanticCache:
    """Cache RAG query responses using exact hash + cosine similarity."""

    HASH_PREFIX = "sc:hash:"
    EMB_STORE = "sc:embeddings"   # Redis hash: key → JSON embedding
    RESP_STORE = "sc:responses"   # Redis hash: key → JSON response

    def __init__(
        self,
        redis_client,
        embedding_service,
        similarity_threshold: float = 0.95,
        ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis_client
        self._embedding = embedding_service
        self._threshold = similarity_threshold
        self._ttl = ttl_seconds

    async def get(self, query: str) -> dict | None:
        """Return cached response or None if cache miss."""
        try:
            # Level 1: exact hash — zero-latency for repeated identical queries
            q_hash = _sha256(query)
            cached = await self._redis.get(f"{self.HASH_PREFIX}{q_hash}")
            if cached:
                logger.debug("SemanticCache: exact hash hit")
                return json.loads(cached)

            # Level 2: embedding similarity
            q_emb = await self._embedding.embed_text(query)
            best_key, best_sim = await self._nearest(q_emb)
            if best_key and best_sim >= self._threshold:
                resp_json = await self._redis.hget(self.RESP_STORE, best_key)
                if resp_json:
                    logger.debug("SemanticCache: similarity hit (sim=%.4f)", best_sim)
                    return json.loads(resp_json)
        except Exception as exc:
            logger.debug("SemanticCache.get failed (non-fatal): %s", exc)
        return None

    async def set(
        self, query: str, response: dict, embedding: list[float] | None = None
    ) -> None:
        """Store query → response in cache."""
        try:
            q_hash = _sha256(query)
            resp_json = json.dumps(response, default=str)

            # Level 1
            await self._redis.setex(
                f"{self.HASH_PREFIX}{q_hash}", self._ttl, resp_json
            )

            # Level 2: embed if not provided
            if embedding is None:
                try:
                    embedding = await self._embedding.embed_text(query)
                except Exception:
                    return

            await self._redis.hset(self.EMB_STORE, q_hash, json.dumps(embedding))
            await self._redis.hset(self.RESP_STORE, q_hash, resp_json)
            # Similarity index gets a longer TTL
            await self._redis.expire(self.EMB_STORE, self._ttl * 10)
            await self._redis.expire(self.RESP_STORE, self._ttl * 10)
        except Exception as exc:
            logger.debug("SemanticCache.set failed (non-fatal): %s", exc)

    async def _nearest(
        self, query_emb: list[float]
    ) -> tuple[str | None, float]:
        try:
            raw = await self._redis.hgetall(self.EMB_STORE)
            if not raw:
                return None, 0.0
            best_key: str | None = None
            best_sim = 0.0
            for k, v in raw.items():
                sim = _cosine(query_emb, json.loads(v))
                if sim > best_sim:
                    best_sim = sim
                    best_key = k if isinstance(k, str) else k.decode()
            return best_key, best_sim
        except Exception as exc:
            logger.debug("SemanticCache._nearest failed: %s", exc)
            return None, 0.0


class EmbeddingCache:
    """Redis hash cache for embedding vectors keyed on (model, text_hash)."""

    CACHE_KEY = "ec:embeddings"

    def __init__(
        self, redis_client, model: str, ttl_seconds: int = 86400
    ) -> None:
        self._redis = redis_client
        self._model = model
        self._ttl = ttl_seconds

    def _field(self, text: str) -> str:
        return f"{self._model}:{_sha256(text)}"

    async def get(self, text: str) -> list[float] | None:
        try:
            raw = await self._redis.hget(self.CACHE_KEY, self._field(text))
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("EmbeddingCache.get failed: %s", exc)
        return None

    async def set(self, text: str, embedding: list[float]) -> None:
        try:
            await self._redis.hset(
                self.CACHE_KEY, self._field(text), json.dumps(embedding)
            )
            await self._redis.expire(self.CACHE_KEY, self._ttl)
        except Exception as exc:
            logger.debug("EmbeddingCache.set failed: %s", exc)


def get_redis_client(url: str):
    """Create an async Redis client from a redis:// URL."""
    try:
        import redis.asyncio as aioredis  # type: ignore
    except ImportError:
        raise ImportError("redis package not installed. Run: pip install redis")
    return aioredis.from_url(url, decode_responses=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
