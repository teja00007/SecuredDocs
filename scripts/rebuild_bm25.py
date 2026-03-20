"""Rebuild BM25 index from Qdrant vector store data.

Reads all chunk payloads from Qdrant (no vectors needed — payload only) and
re-indexes them into the BM25 in-memory index saved to data/bm25_index.json.

Run from project root:
    python scripts/rebuild_bm25.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    from src.config import get_settings
    from src.services.bm25_service import BM25Service

    settings = get_settings()
    qdrant_url = os.environ.get("QDRANT_URL", getattr(settings, "QDRANT_URL", "http://localhost:6333"))

    try:
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.http import models as qmodels
    except ImportError:
        print("qdrant-client not installed — skipping BM25 rebuild.")
        return

    client = AsyncQdrantClient(url=qdrant_url)
    COLLECTION = "rag_documents"

    # Check collection exists
    try:
        collections = await client.get_collections()
        names = [c.name for c in collections.collections]
        if COLLECTION not in names:
            print(f"Collection '{COLLECTION}' does not exist in Qdrant — nothing to index.")
            await client.close()
            return
        info = await client.get_collection(COLLECTION)
        total = info.points_count or 0
    except Exception as e:
        print(f"Cannot connect to Qdrant at {qdrant_url}: {e}")
        return

    print(f"Connected to Qdrant at {qdrant_url} — {total} points in '{COLLECTION}'")

    # Scroll through all points (payload only — skip vectors)
    all_chunks = []
    offset = None
    batch_size = 200
    fetched = 0

    while True:
        result, next_offset = await client.scroll(
            collection_name=COLLECTION,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in result:
            payload = point.payload or {}
            chunk_id = str(point.id)
            text = payload.get("text", "")
            bm25_meta: dict = {}
            for k, v in payload.items():
                if k == "text":
                    continue
                if isinstance(v, (str, int, float, bool)):
                    bm25_meta[k] = v
                elif v is None:
                    bm25_meta[k] = ""
                elif isinstance(v, list) and all(isinstance(x, str) for x in v):
                    bm25_meta[k] = v
                else:
                    bm25_meta[k] = str(v)
            all_chunks.append({"id": chunk_id, "text": text, "metadata": bm25_meta})

        fetched += len(result)
        if total:
            print(f"  Fetched {fetched}/{total} chunks...", end="\r", flush=True)

        if next_offset is None:
            break
        offset = next_offset

    await client.close()
    print(f"\nFetched {len(all_chunks)} chunks from Qdrant.")

    if not all_chunks:
        print("No chunks found — BM25 index not rebuilt.")
        return

    # Reset BM25 singleton and rebuild
    BM25Service._instance = None
    bm25 = BM25Service()
    bm25.add_chunks(all_chunks)
    print(f"BM25 index rebuilt: {len(bm25._chunk_store)} chunks indexed.")
    print("Saved to data/bm25_index.json")

    # Sanity check
    results = bm25.search("onboarding first week checklist", top_k=3)
    print(f"\nSanity check — top 3 for 'onboarding first week checklist':")
    for r in results:
        fn = r["metadata"].get("filename", "?")
        print(f"  score={r['score']:.4f}  {fn}: {r['text'][:80]}...")


if __name__ == "__main__":
    asyncio.run(main())
