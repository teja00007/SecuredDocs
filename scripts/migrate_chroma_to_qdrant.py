#!/usr/bin/env python3
"""Migrate all vectors from ChromaDB to Qdrant.

Run once after bringing up the Qdrant service:
  python scripts/migrate_chroma_to_qdrant.py

The script:
1. Connects to the existing ChromaDB collection
2. Reads all documents in batches
3. Upserts them into Qdrant using the same IDs
4. Reports progress

Safe to re-run — Qdrant upsert is idempotent.
"""

import asyncio
import os
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
BATCH_SIZE = 100


async def migrate():
    print(f"ChromaDB source: {CHROMA_PERSIST_DIR}")
    print(f"Qdrant target:   {QDRANT_URL}")

    # Connect to ChromaDB
    try:
        import chromadb
        chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        collections = chroma_client.list_collections()
        print(f"Found {len(collections)} ChromaDB collection(s)")
    except Exception as e:
        print(f"ERROR: Could not connect to ChromaDB: {e}")
        sys.exit(1)

    # Connect to Qdrant
    try:
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.http import models as qmodels
        qdrant = AsyncQdrantClient(url=QDRANT_URL)
    except Exception as e:
        print(f"ERROR: Could not connect to Qdrant: {e}")
        sys.exit(1)

    total_migrated = 0

    for col in collections:
        chroma_col = chroma_client.get_collection(col.name)
        count = chroma_col.count()
        print(f"\nMigrating collection '{col.name}' ({count} documents)...")

        # Ensure Qdrant collection exists
        qdrant_col_name = "rag_documents"
        existing_cols = await qdrant.get_collections()
        existing_names = [c.name for c in existing_cols.collections]

        if qdrant_col_name not in existing_names:
            # Detect vector dimensions from first batch
            first = chroma_col.get(limit=1, include=["embeddings"])
            dims = len(first["embeddings"][0]) if first["embeddings"] else 768
            await qdrant.create_collection(
                collection_name=qdrant_col_name,
                vectors_config=qmodels.VectorParams(
                    size=dims,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            print(f"  Created Qdrant collection '{qdrant_col_name}' (dims={dims})")

        # Migrate in batches
        offset = 0
        while True:
            batch = chroma_col.get(
                limit=BATCH_SIZE,
                offset=offset,
                include=["embeddings", "documents", "metadatas"],
            )
            if not batch["ids"]:
                break

            points = []
            for i, doc_id in enumerate(batch["ids"]):
                embedding = batch["embeddings"][i] if batch["embeddings"] else None
                if embedding is None:
                    continue
                metadata = batch["metadatas"][i] if batch["metadatas"] else {}
                text = batch["documents"][i] if batch["documents"] else ""
                payload = dict(metadata)
                payload["text"] = text

                import uuid as _uuid
                try:
                    point_id = str(_uuid.UUID(doc_id))
                except ValueError:
                    point_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, doc_id))

                points.append(qmodels.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload,
                ))

            if points:
                await qdrant.upsert(
                    collection_name=qdrant_col_name,
                    points=points,
                )
                total_migrated += len(points)
                print(f"  Migrated {offset + len(points)}/{count}...", end="\r")

            offset += BATCH_SIZE
            if offset >= count:
                break

        print(f"  Done: {col.name} → {qdrant_col_name}")

    print(f"\n✅ Migration complete. Total vectors migrated: {total_migrated}")
    await qdrant.close()


if __name__ == "__main__":
    asyncio.run(migrate())
