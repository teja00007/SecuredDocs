"""Qdrant vector store implementation.

Uses qdrant-client (async). Set VECTOR_STORE_TYPE=qdrant in .env.
Start Qdrant: docker run -p 6333:6333 qdrant/qdrant

Sparse vector support (BM25 via fastembed)
------------------------------------------
When ``fastembed`` is installed and ``QDRANT_SPARSE_ENABLED=true``, every
inserted chunk also gets a sparse BM25 vector stored under the ``"sparse"``
named vector slot.  This replaces the in-memory rank_bm25 Lane 2 in the
parallel pipeline with a native Qdrant sparse index, which is more memory-
efficient and survives restarts without re-indexing.

Install: pip install fastembed
"""

import uuid
import logging

from src.core.exceptions import VectorStoreError
from src.core.interfaces import IVectorStore, ChunkResult

logger = logging.getLogger(__name__)

try:
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http import models as qmodels
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False

try:
    from fastembed import SparseTextEmbedding as _SparseTextEmbedding
    _FASTEMBED_AVAILABLE = True
except ImportError:
    _FASTEMBED_AVAILABLE = False


class QdrantStore(IVectorStore):
    """Qdrant-backed vector store with full RBAC metadata filtering.

    When fastembed is installed and sparse_enabled=True, the collection
    stores both dense (cosine) and sparse (BM25) vectors enabling native
    Qdrant hybrid search without an external BM25 index.
    """

    COLLECTION_NAME = "rag_documents"

    def __init__(
        self,
        url: str,
        api_key: str = "",
        dimensions: int = 768,
        sparse_enabled: bool = False,
    ) -> None:
        if not _QDRANT_AVAILABLE:
            raise VectorStoreError("qdrant-client is not installed. Run: pip install qdrant-client")
        self._url = url
        self._api_key = api_key or None
        self._dimensions = dimensions
        self._sparse_enabled = sparse_enabled and _FASTEMBED_AVAILABLE
        self._client: AsyncQdrantClient | None = None
        self._bm25_model = None  # lazy-loaded SparseTextEmbedding

    def _get_bm25_model(self):
        """Lazy-load the fastembed BM25 model (heavy first call)."""
        if self._bm25_model is None and _FASTEMBED_AVAILABLE:
            self._bm25_model = _SparseTextEmbedding(model_name="Qdrant/bm25")
        return self._bm25_model

    def _encode_sparse(self, text: str) -> "qmodels.SparseVector | None":
        """Return a Qdrant SparseVector for text, or None on failure."""
        model = self._get_bm25_model()
        if model is None:
            return None
        try:
            result = list(model.embed([text]))
            sv = result[0]
            return qmodels.SparseVector(
                indices=sv.indices.tolist(),
                values=sv.values.tolist(),
            )
        except Exception as exc:
            logger.debug("BM25 sparse encode failed (non-fatal): %s", exc)
            return None

    async def _get_client(self) -> "AsyncQdrantClient":
        if self._client is None:
            self._client = AsyncQdrantClient(url=self._url, api_key=self._api_key)
            await self._ensure_collection()
        return self._client

    async def _ensure_collection(self) -> None:
        client = self._client
        collections = await client.get_collections()
        names = [c.name for c in collections.collections]
        if self.COLLECTION_NAME not in names:
            sparse_config = None
            if self._sparse_enabled:
                sparse_config = {
                    "sparse": qmodels.SparseVectorParams(
                        index=qmodels.SparseIndexParams(on_disk=False)
                    )
                }
            await client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=qmodels.VectorParams(
                    size=self._dimensions,
                    distance=qmodels.Distance.COSINE,
                ),
                sparse_vectors_config=sparse_config,
            )

    async def insert(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        client = await self._get_client()
        points = []
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", str(uuid.uuid4()))
            payload = {k: v for k, v in chunk.items() if k not in ("chunk_id", "embedding")}

            # Build vector dict — always dense, optionally + sparse BM25
            vectors: dict | list = chunk["embedding"]
            if self._sparse_enabled:
                text = chunk.get("text", "")
                sparse_vec = self._encode_sparse(text) if text else None
                if sparse_vec is not None:
                    vectors = {
                        "": chunk["embedding"],  # unnamed dense slot
                        "sparse": sparse_vec,
                    }

            points.append(qmodels.PointStruct(
                id=self._str_to_uuid(chunk_id),
                vector=vectors,
                payload=payload,
            ))
        try:
            await client.upsert(collection_name=self.COLLECTION_NAME, points=points)
        except Exception as e:
            raise VectorStoreError(f"Qdrant insert failed: {e}")

    async def search(
        self, embedding: list[float], filter: dict, top_k: int = 5
    ) -> list[ChunkResult]:
        client = await self._get_client()
        qdrant_filter = self._translate_filter(filter) if filter else None
        try:
            # qdrant-client >=1.10 uses query_points() instead of search()
            response = await client.query_points(
                collection_name=self.COLLECTION_NAME,
                query=embedding,
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
            results = response.points
        except Exception as e:
            raise VectorStoreError(f"Qdrant search failed: {e}")

        chunks: list[ChunkResult] = []
        for hit in results:
            payload = hit.payload or {}
            chunks.append(ChunkResult(
                chunk_id=str(hit.id),
                document_id=payload.get("document_id", ""),
                text=payload.get("text", ""),
                metadata=payload,
                score=float(hit.score),
            ))
        return chunks

    async def sparse_search(
        self, query_text: str, filter: dict, top_k: int = 5
    ) -> list[ChunkResult]:
        """BM25 sparse vector search (requires QDRANT_SPARSE_ENABLED=true + fastembed).

        Returns an empty list when sparse vectors are not configured.
        """
        if not self._sparse_enabled:
            return []

        sparse_vec = self._encode_sparse(query_text)
        if sparse_vec is None:
            return []

        client = await self._get_client()
        qdrant_filter = self._translate_filter(filter) if filter else None
        try:
            response = await client.query_points(
                collection_name=self.COLLECTION_NAME,
                query=sparse_vec,
                using="sparse",
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
            results = response.points
        except Exception as e:
            logger.debug("Qdrant sparse_search failed (non-fatal): %s", e)
            return []

        chunks: list[ChunkResult] = []
        for hit in results:
            payload = hit.payload or {}
            chunks.append(ChunkResult(
                chunk_id=str(hit.id),
                document_id=payload.get("document_id", ""),
                text=payload.get("text", ""),
                metadata=payload,
                score=float(hit.score),
            ))
        return chunks

    async def delete_by_document_id(self, document_id: str) -> int:
        client = await self._get_client()
        try:
            result = await client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=document_id),
                        )]
                    )
                ),
            )
            return getattr(result, "result", 0) or 0
        except Exception as e:
            raise VectorStoreError(f"Qdrant delete failed: {e}")

    async def update_metadata(self, document_id: str, metadata: dict) -> None:
        client = await self._get_client()
        try:
            await client.set_payload(
                collection_name=self.COLLECTION_NAME,
                payload=metadata,
                points=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="document_id",
                        match=qmodels.MatchValue(value=document_id),
                    )]
                ),
            )
        except Exception as e:
            raise VectorStoreError(f"Qdrant update_metadata failed: {e}")

    async def count(self) -> int:
        client = await self._get_client()
        try:
            info = await client.get_collection(self.COLLECTION_NAME)
            return info.points_count or 0
        except Exception as e:
            raise VectorStoreError(f"Qdrant count failed: {e}")

    async def delete_all(self) -> None:
        """Delete the entire collection (used by reset scripts)."""
        client = await self._get_client()
        try:
            await client.delete_collection(self.COLLECTION_NAME)
        except Exception:
            pass

    # ── Filter translation ────────────────────────────────────────────────────

    def _translate_filter(self, generic_filter: dict) -> "qmodels.Filter | None":
        if not generic_filter:
            return None
        or_clauses = generic_filter.get("$or", [])
        if not or_clauses:
            return self._translate_clause(generic_filter)

        should = []
        for clause in or_clauses:
            translated = self._translate_clause(clause)
            if translated:
                should.extend(translated.must or [])

        return qmodels.Filter(should=should) if should else None

    def _translate_clause(self, clause: dict) -> "qmodels.Filter | None":
        conditions = []
        for key, value in clause.items():
            if key == "visibility":
                conditions.append(qmodels.FieldCondition(
                    key="visibility", match=qmodels.MatchValue(value=value)
                ))
            elif key == "owner_id":
                conditions.append(qmodels.FieldCondition(
                    key="owner_id", match=qmodels.MatchValue(value=value)
                ))
            elif key == "allowed_teams" and isinstance(value, list):
                for tid in value:
                    conditions.append(qmodels.FieldCondition(
                        key="allowed_teams", match=qmodels.MatchText(text=f"|{tid}|")
                    ))
            elif key == "allowed_users" and isinstance(value, list):
                for uid in value:
                    conditions.append(qmodels.FieldCondition(
                        key="allowed_users", match=qmodels.MatchText(text=f"|{uid}|")
                    ))
            elif key == "company_id":
                conditions.append(qmodels.FieldCondition(
                    key="company_id", match=qmodels.MatchValue(value=value)
                ))
            elif key == "collection_id":
                inner = value
                if isinstance(inner, dict) and "$eq" in inner:
                    inner = inner["$eq"]
                conditions.append(qmodels.FieldCondition(
                    key="collection_id", match=qmodels.MatchValue(value=inner)
                ))
        if not conditions:
            return None
        return qmodels.Filter(must=conditions)

    @staticmethod
    def _str_to_uuid(s: str) -> str:
        # Qdrant point IDs must be unsigned integers or UUID strings
        try:
            return str(uuid.UUID(s))
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, s))
