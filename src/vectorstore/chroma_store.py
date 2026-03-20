"""ChromaDB vector store implementation."""

import asyncio
import uuid

import chromadb

from src.core.exceptions import VectorStoreError
from src.core.interfaces import IVectorStore, ChunkResult


class ChromaStore(IVectorStore):
    """ChromaDB-backed vector store with RBAC metadata filtering."""

    COLLECTION_NAME = "rag_documents"

    def __init__(self, persist_dir: str) -> None:
        try:
            self._client = chromadb.PersistentClient(path=persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            raise VectorStoreError(f"Failed to initialize ChromaDB: {e}")

    async def insert(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        try:
            await asyncio.to_thread(self._insert_sync, chunks)
        except Exception as e:
            raise VectorStoreError(f"ChromaDB insert failed: {e}")

    def _insert_sync(self, chunks: list[dict]) -> None:
        ids = [c.get("chunk_id", str(uuid.uuid4())) for c in chunks]
        embeddings = [c["embedding"] for c in chunks]
        documents = [c["text"] for c in chunks]
        metadatas = []
        for c in chunks:
            meta = {k: v for k, v in c.items() if k not in ("chunk_id", "embedding", "text")}
            # ChromaDB requires scalar metadata values
            cleaned = self._flatten_metadata(meta)
            metadatas.append(cleaned)

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def _flatten_metadata(self, meta: dict) -> dict:
        """Convert lists/complex types to ChromaDB-compatible scalars."""
        flat: dict = {}
        for k, v in meta.items():
            if isinstance(v, list):
                # Wrap with leading/trailing pipes so "|id|" substring checks work
                flat[k] = "|" + "|".join(str(x) for x in v) + "|" if v else ""
            elif isinstance(v, (str, int, float, bool)):
                flat[k] = v
            elif v is None:
                flat[k] = ""
            else:
                flat[k] = str(v)
        return flat

    async def search(
        self, embedding: list[float], filter: dict, top_k: int = 5
    ) -> list[ChunkResult]:
        try:
            results = await asyncio.to_thread(
                self._search_sync, embedding, filter, top_k
            )
            return results
        except Exception as e:
            raise VectorStoreError(f"ChromaDB search failed: {e}")

    def _search_sync(
        self, embedding: list[float], filter: dict, top_k: int
    ) -> list[ChunkResult]:
        # Step 1: Build a simple, flat ChromaDB where clause that only uses $eq/$or
        # (avoids nested $and inside $or which can cause issues in some ChromaDB versions).
        # We over-fetch and post-filter in Python for team/channel conditions.
        simple_where = self._make_simple_where(filter) if filter else None
        # Over-fetch so that Python post-filtering still yields enough results.
        # Use a larger multiplier (10×) to improve recall across large indexes.
        fetch_n = top_k * 10 if filter else top_k

        # Guard: ChromaDB requires n_results <= collection size
        col_count = self._collection.count()
        if col_count == 0:
            return []
        fetch_n = min(fetch_n, col_count)

        kwargs: dict = {
            "query_embeddings": [embedding],
            "n_results": fetch_n,
            "include": ["documents", "metadatas", "distances"],
        }
        if simple_where:
            kwargs["where"] = simple_where

        try:
            results = self._collection.query(**kwargs)
        except Exception:
            # If the simple filter also fails, search without any filter
            kwargs.pop("where", None)
            fetch_n = min(top_k * 4, col_count)
            kwargs["n_results"] = fetch_n
            results = self._collection.query(**kwargs)

        chunks: list[ChunkResult] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for chunk_id, doc, meta, dist in zip(ids, docs, metas, distances):
            score = 1.0 - dist  # cosine distance → similarity
            chunks.append(ChunkResult(
                chunk_id=chunk_id,
                document_id=meta.get("document_id", ""),
                text=doc,
                metadata=meta,
                score=score,
            ))

        # Step 2: Python post-filter — apply the full RBAC logic precisely.
        # This handles allowed_teams and allowed_users checks that can't be
        # expressed as simple ChromaDB where clauses.
        if filter:
            chunks = [c for c in chunks if self._chunk_passes_rbac(c.metadata, filter)]

        return chunks[:top_k]

    def _make_simple_where(self, generic_filter: dict) -> dict | None:
        """Build a ChromaDB-safe where clause using only flat $eq/$or conditions.

        For the RBAC $or filter we extract only the visibility and owner_id
        equality conditions — the complex allowed_teams/$contains checks are
        deferred to the Python post-filter (_chunk_passes_rbac).
        """
        if not generic_filter:
            return None

        # Handle top-level $and wrapper (produced by _apply_collection_filter when
        # both an RBAC filter and a collection_id are active).
        and_parts = generic_filter.get("$and", [])
        if and_parts and "$or" not in generic_filter:
            sub_clauses = [self._make_simple_where(p) for p in and_parts]
            sub_clauses = [s for s in sub_clauses if s]
            if not sub_clauses:
                return None
            if len(sub_clauses) == 1:
                return sub_clauses[0]
            return {"$and": sub_clauses}

        or_clauses = generic_filter.get("$or", [])
        if not or_clauses:
            # Single-clause filter (e.g. collection_id = x)
            return self._translate_single_clause(generic_filter)

        simple_clauses = []
        for clause in or_clauses:
            # Top-level $and (e.g. collection + RBAC combined)
            if "$and" in clause:
                # Each inner clause is itself a simple filter; recurse
                inner = self._make_simple_where(clause)
                if inner:
                    simple_clauses.append(inner)
                continue

            # Extract only the owner_id and visibility keys — skip allowed_teams/allowed_users
            simple: dict = {}
            if "owner_id" in clause:
                simple["owner_id"] = {"$eq": clause["owner_id"]}
            if "visibility" in clause:
                simple["visibility"] = {"$eq": clause["visibility"]}

            if simple:
                if len(simple) == 1:
                    k, v = next(iter(simple.items()))
                    simple_clauses.append({k: v})
                else:
                    simple_clauses.append({"$and": [{k: v} for k, v in simple.items()]})

        if not simple_clauses:
            return None
        if len(simple_clauses) == 1:
            return simple_clauses[0]
        return {"$or": simple_clauses}

    def _chunk_passes_rbac(self, meta: dict, rbac_filter: dict) -> bool:
        """Return True if chunk metadata passes the full RBAC filter."""
        # Empty filter = admin, no restriction
        if not rbac_filter:
            return True

        or_clauses = rbac_filter.get("$or", [])
        and_clauses = rbac_filter.get("$and", [])

        if or_clauses:
            return any(self._clause_matches(meta, c) for c in or_clauses)
        if and_clauses:
            return all(self._clause_matches(meta, c) for c in and_clauses)
        return self._clause_matches(meta, rbac_filter)

    def _clause_matches(self, meta: dict, clause: dict) -> bool:
        """Evaluate a single filter clause against chunk metadata."""
        or_inner = clause.get("$or")
        and_inner = clause.get("$and")
        if or_inner:
            return any(self._clause_matches(meta, c) for c in or_inner)
        if and_inner:
            return all(self._clause_matches(meta, c) for c in and_inner)

        for key, value in clause.items():
            if key in ("$and", "$or"):
                continue
            meta_val = meta.get(key, "")
            if key in ("allowed_teams", "allowed_users"):
                # value is a list of IDs; check pipe-delimited string.
                # Wrap meta_val with pipes so "|id|" checks work for both
                # old ("a|b") and new ("|a|b|") storage formats.
                wrapped = f"|{meta_val}|"
                if isinstance(value, list):
                    if not any(f"|{v}|" in wrapped for v in value):
                        return False
                else:
                    if f"|{value}|" not in wrapped:
                        return False
            elif isinstance(value, dict) and "$eq" in value:
                if meta_val != value["$eq"]:
                    return False
            elif isinstance(value, dict) and "$contains" in value:
                if value["$contains"] not in str(meta_val):
                    return False
            else:
                if meta_val != value:
                    return False
        return True

    def _translate_filter(self, generic_filter: dict) -> dict | None:
        """Translate the generic RBAC filter to ChromaDB where clause.

        For simplicity, we extract document_id lists from owner/visibility clauses
        and use $in. For production, use Qdrant which has richer filtering.
        """
        # Empty filter = admin access = no restriction
        if not generic_filter:
            return None

        or_clauses = generic_filter.get("$or", [])
        if not or_clauses:
            return self._translate_single_clause(generic_filter)

        chroma_clauses = []
        for clause in or_clauses:
            translated = self._translate_single_clause(clause)
            if translated:
                chroma_clauses.append(translated)

        if not chroma_clauses:
            return None
        if len(chroma_clauses) == 1:
            return chroma_clauses[0]
        return {"$or": chroma_clauses}

    def _translate_single_clause(self, clause: dict) -> dict | None:
        if not clause:
            return None

        conditions = []
        for key, value in clause.items():
            if key == "visibility":
                conditions.append({"visibility": {"$eq": value}})
            elif key == "owner_id":
                conditions.append({"owner_id": {"$eq": value}})
            elif key == "allowed_teams" and isinstance(value, list):
                # Match any team — use OR with $contains
                if value:
                    team_conds = [
                        {"allowed_teams": {"$contains": f"|{tid}|"}}
                        for tid in value
                    ]
                    if len(team_conds) == 1:
                        conditions.append(team_conds[0])
                    else:
                        conditions.append({"$or": team_conds})
            elif key == "allowed_users" and isinstance(value, list):
                if value:
                    user_conds = [
                        {"allowed_users": {"$contains": f"|{uid}|"}}
                        for uid in value
                    ]
                    if len(user_conds) == 1:
                        conditions.append(user_conds[0])
                    else:
                        conditions.append({"$or": user_conds})
            elif key not in ("$and", "$or") and isinstance(value, dict) and "$eq" in value:
                conditions.append({key: value})
            elif key not in ("$and", "$or") and isinstance(value, str):
                conditions.append({key: {"$eq": value}})
            elif key not in ("$and", "$or") and isinstance(value, (int, float, bool)):
                conditions.append({key: {"$eq": value}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    async def delete_by_document_id(self, document_id: str) -> int:
        try:
            existing = await asyncio.to_thread(
                self._collection.get,
                where={"document_id": {"$eq": document_id}},
                include=[],
            )
            ids = existing.get("ids", [])
            if ids:
                await asyncio.to_thread(self._collection.delete, ids=ids)
            return len(ids)
        except Exception as e:
            raise VectorStoreError(f"ChromaDB delete failed: {e}")

    async def delete_all(self) -> None:
        """Delete the entire collection and recreate it empty."""
        try:
            await asyncio.to_thread(self._client.delete_collection, self.COLLECTION_NAME)
            self._collection = await asyncio.to_thread(
                self._client.get_or_create_collection,
                self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            raise VectorStoreError(f"ChromaDB delete_all failed: {e}")

    async def update_metadata(self, document_id: str, metadata: dict) -> None:
        try:
            existing = await asyncio.to_thread(
                self._collection.get,
                where={"document_id": {"$eq": document_id}},
                include=["metadatas"],
            )
            ids = existing.get("ids", [])
            if not ids:
                return
            metas = existing.get("metadatas", [])
            updated_metas = []
            flat_update = self._flatten_metadata(metadata)
            for m in metas:
                merged = dict(m)
                merged.update(flat_update)
                updated_metas.append(merged)
            await asyncio.to_thread(
                self._collection.update, ids=ids, metadatas=updated_metas
            )
        except Exception as e:
            raise VectorStoreError(f"ChromaDB update_metadata failed: {e}")

    async def count(self) -> int:
        try:
            return await asyncio.to_thread(self._collection.count)
        except Exception as e:
            raise VectorStoreError(f"ChromaDB count failed: {e}")
